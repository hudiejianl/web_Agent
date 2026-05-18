from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agents.advisor_agent import AdvisorAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.planner_agent import PlannerAgent
from app.models.schemas import AgentHandoff, AgentPlan, AgentTrace, MemoryState, RelevantMemory, RetrievalEvidence, TutorProfile
from app.rag.evidence import RetrievalEvidenceBuilder
from app.rag.retriever import TutorRetriever
from app.services.ingestion import IngestionService
from app.storage.repositories import PlanRepository


class AdmissionState(TypedDict, total=False):
    session_id: str
    message: str
    memory: MemoryState
    plan: AgentPlan
    tutors: list[TutorProfile]
    retrieval_evidence: list[RetrievalEvidence]
    relevant_memories: list[RelevantMemory]
    agent_handoffs: list[AgentHandoff]
    ingested_tutors: list[TutorProfile]
    answer: str
    trace: list[AgentTrace]


class AdmissionGraph:
    def __init__(self):
        self.memory_agent = MemoryAgent()
        self.planner_agent = PlannerAgent()
        self.retriever = TutorRetriever()
        self.evidence_builder = RetrievalEvidenceBuilder()
        self.ingestion = IngestionService()
        self.plans = PlanRepository()
        self.advisor = AdvisorAgent()
        self.graph = self._build()

    def invoke(self, session_id: str, message: str) -> AdmissionState:
        return self.graph.invoke({"session_id": session_id, "message": message})

    def _build(self):
        # 主工作流按“记忆 → 规划 → 检索/采集 → 建议 → 更新记忆”串联。
        graph = StateGraph(AdmissionState)
        graph.add_node("load_memory_node", self._load_memory)
        graph.add_node("plan_node", self._plan)
        graph.add_node("ingest_node", self._ingest)
        graph.add_node("retrieve_node", self._retrieve)
        graph.add_node("advise_node", self._advise)
        graph.add_node("save_memory_node", self._save_memory)
        graph.set_entry_point("load_memory_node")
        graph.add_edge("load_memory_node", "plan_node")
        graph.add_conditional_edges("plan_node", self._route_after_plan, {"ingest": "ingest_node", "retrieve": "retrieve_node"})
        graph.add_edge("ingest_node", "retrieve_node")
        graph.add_edge("retrieve_node", "advise_node")
        graph.add_edge("advise_node", "save_memory_node")
        graph.add_edge("save_memory_node", END)
        return graph.compile()

    def _load_memory(self, state: AdmissionState) -> AdmissionState:
        state["trace"] = []
        state["agent_handoffs"] = []
        state["memory"] = self.memory_agent.load(state["session_id"])
        state["relevant_memories"] = self.memory_agent.retrieve_relevant(state["memory"], state["message"])
        self._trace(
            state,
            "Memory Agent",
            "load_memory",
            "completed",
            f"加载会话 {state['session_id']} 的长期记忆，已记录 {len(state['memory'].recent_messages)} 条近期消息",
        )
        self._trace(
            state,
            "Memory Agent",
            "retrieve_relevant_memory",
            "completed",
            f"召回 {len(state['relevant_memories'])} 条相关历史记忆",
            {"memory_count": len(state["relevant_memories"])},
        )
        self._handoff(
            state,
            "Memory Agent",
            "Planner Agent",
            "memory_context",
            f"用户画像方向 {len(state['memory'].profile.research_interests)} 项，相关记忆 {len(state['relevant_memories'])} 条",
            {
                "research_interests": state["memory"].profile.research_interests,
                "preferred_locations": state["memory"].profile.preferred_locations,
                "target_degree": state["memory"].profile.target_degree or "",
                "relevant_memory_count": len(state["relevant_memories"]),
            },
        )
        return state

    def _plan(self, state: AdmissionState) -> AdmissionState:
        previous_runs = self.plans.list_by_session(state["session_id"], limit=1)
        previous_run = previous_runs[0] if previous_runs else None
        previous_constraints = previous_run.plan.constraints if previous_run else []
        state["plan"] = self.planner_agent.plan(
            state["message"],
            previous_plan_id=previous_run.plan_id if previous_run else None,
            previous_constraints=previous_constraints,
        )
        self._trace(
            state,
            "Planner Agent",
            "replan_task" if state["plan"].is_replan else "decompose_task",
            "completed",
            f"生成 {len(state['plan'].steps)} 个执行步骤，约束：{', '.join(state['plan'].constraints) or '无显式约束'}",
            {"step_count": len(state["plan"].steps), "is_replan": state["plan"].is_replan, "replan_from": state["plan"].replan_from or ""},
        )
        self._handoff(
            state,
            "Planner Agent",
            "Browser Agent" if state["plan"].need_ingestion else "RAG Retriever",
            "task_plan",
            f"计划 {len(state['plan'].steps)} 步，检索={state['plan'].need_retrieval}，采集={state['plan'].need_ingestion}",
            {
                "constraints": state["plan"].constraints,
                "step_ids": [step.id for step in state["plan"].steps],
                "urls": state["plan"].urls,
                "is_replan": state["plan"].is_replan,
            },
        )
        return state

    def _route_after_plan(self, state: AdmissionState) -> str:
        return "ingest" if state["plan"].need_ingestion else "retrieve"

    def _ingest(self, state: AdmissionState) -> AdmissionState:
        step = self._mark_step(state, "Browser Agent", "running")
        ingested: list[TutorProfile] = []
        errors: list[str] = []
        for url in state["plan"].urls:
            try:
                ingested.append(self.ingestion.ingest_url(url))
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        state["ingested_tutors"] = ingested
        if step:
            step.outputs = {"ingested_count": len(ingested), "tutors": [tutor.name for tutor in ingested]}
            if errors:
                step.error = "；".join(errors)
        status = "completed" if ingested else "failed" if errors else "skipped"
        self._mark_step_by_id(state, "ingest_urls", status)
        self._trace(
            state,
            "Browser Agent",
            "ingest_urls",
            status,
            f"采集并入库 {len(ingested)} 个导师主页" + (f"，失败 {len(errors)} 个" if errors else ""),
            {"ingested_count": len(ingested), "failed_count": len(errors)},
        )
        self._handoff(
            state,
            "Browser Agent",
            "RAG Retriever",
            "ingested_profiles",
            f"新增入库 {len(ingested)} 位导师，失败 {len(errors)} 个 URL",
            {"tutors": [tutor.name for tutor in ingested], "errors": errors[:3]},
        )
        return state

    def _retrieve(self, state: AdmissionState) -> AdmissionState:
        self._mark_step(state, "RAG Retriever", "running")
        memory = state["memory"]
        profile_terms = " ".join(memory.profile.research_interests + memory.profile.preferred_locations)
        query = f"{state['message']} {profile_terms} {memory.profile.target_degree or ''}"
        state["tutors"] = self.retriever.search(query, limit=5)
        state["retrieval_evidence"] = self.evidence_builder.build(query, state["tutors"])
        retrieve_step = self._mark_step(state, "RAG Retriever", "completed")
        if retrieve_step:
            retrieve_step.outputs = {
                "result_count": len(state["tutors"]),
                "tutors": [tutor.name for tutor in state["tutors"]],
                "evidence_count": len(state["retrieval_evidence"]),
            }
        research_status = "completed" if state["tutors"] else "skipped"
        for step_id in ["check_recent_papers", "analyze_research_fit", "check_admission_status"]:
            research_step = self._mark_step_by_id(state, step_id, research_status)
            if research_step:
                research_step.outputs = self._research_step_outputs(step_id, state)
        self._trace(
            state,
            "RAG Retriever",
            "retrieve_tutors",
            "completed",
            f"基于用户问题和长期偏好召回 {len(state['tutors'])} 位候选导师，形成 {len(state['retrieval_evidence'])} 条分字段证据",
            {"result_count": len(state["tutors"]), "evidence_count": len(state["retrieval_evidence"])},
        )
        self._trace(
            state,
            "Research Agent",
            "analyze_candidates",
            "completed" if state["tutors"] else "skipped",
            "已依据研究方向、招生方向、论文和证据片段形成匹配基础" if state["tutors"] else "本地知识库暂无候选导师，跳过候选分析",
        )
        self._handoff(
            state,
            "RAG Retriever",
            "Research Agent",
            "retrieval_results",
            f"召回 {len(state['tutors'])} 位导师，证据 {len(state['retrieval_evidence'])} 条",
            {
                "query": query,
                "tutors": [tutor.name for tutor in state["tutors"]],
                "evidence_fields": list(dict.fromkeys(item.field for item in state["retrieval_evidence"])),
            },
        )
        self._handoff(
            state,
            "Research Agent",
            "Advisor Agent",
            "candidate_analysis",
            f"分析 {len(state['tutors'])} 位候选导师，形成推荐输入",
            {
                "candidate_count": len(state["tutors"]),
                "top_candidates": [tutor.name for tutor in state["tutors"][:3]],
                "evidence_count": len(state["retrieval_evidence"]),
            },
        )
        return state

    def _advise(self, state: AdmissionState) -> AdmissionState:
        self._mark_step(state, "Advisor Agent", "running")
        state["answer"], llm_result = self.advisor.answer(
            state["message"],
            state.get("tutors", []),
            state["memory"],
            state.get("plan"),
            state.get("retrieval_evidence", []),
            state.get("relevant_memories", []),
        )
        if llm_result.used_fallback:
            self._trace(
                state,
                "LLM Agent",
                "generate_advice",
                "skipped",
                f"未使用大模型，原因：{llm_result.error or 'LLM 未配置'}",
                {"provider": llm_result.provider, "model": llm_result.model},
            )
        else:
            self._trace(
                state,
                "LLM Agent",
                "generate_advice",
                "completed",
                f"通过 {llm_result.provider} 模型 {llm_result.model} 生成个性化推荐",
                {"provider": llm_result.provider, "model": llm_result.model},
            )
        score_step = self._mark_step_by_id(state, "score_candidates", "completed")
        if score_step:
            score_step.outputs = {
                "scored_count": len(state.get("tutors", [])),
                "top_candidates": [tutor.name for tutor in state.get("tutors", [])[:3]],
            }
        advice_step = self._mark_step_by_id(state, "generate_advice", "completed")
        if advice_step:
            advice_step.outputs = {"answer_length": len(state["answer"]), "used_llm": not llm_result.used_fallback}
        self._trace(
            state,
            "Advisor Agent",
            "generate_recommendation",
            "completed",
            "生成带证据、匹配理由和下一步行动的升学建议",
        )
        self._handoff(
            state,
            "Advisor Agent",
            "Memory Agent",
            "conversation_outcome",
            f"生成 {len(state['answer'])} 字建议，准备写入长期记忆",
            {"answer_length": len(state["answer"]), "used_llm": not llm_result.used_fallback},
        )
        return state

    def _save_memory(self, state: AdmissionState) -> AdmissionState:
        state["memory"] = self.memory_agent.update(state["session_id"], state["message"], state["answer"])
        self._trace(
            state,
            "Memory Agent",
            "update_memory",
            "completed",
            f"更新用户画像：方向 {len(state['memory'].profile.research_interests)} 项，地区 {len(state['memory'].profile.preferred_locations)} 项",
        )
        return state

    def _trace(
        self,
        state: AdmissionState,
        agent: str,
        action: str,
        status: str,
        detail: str,
        metadata: dict[str, str | int | float | bool] | None = None,
    ) -> None:
        state.setdefault("trace", []).append(
            AgentTrace(agent=agent, action=action, status=status, detail=detail, metadata=metadata or {})
        )

    def _handoff(self, state: AdmissionState, source_agent: str, target_agent: str, payload_type: str, summary: str, payload: dict) -> None:
        state.setdefault("agent_handoffs", []).append(
            AgentHandoff(source_agent=source_agent, target_agent=target_agent, payload_type=payload_type, summary=summary, payload=payload)
        )
        self._trace(
            state,
            source_agent,
            "handoff_context",
            "completed",
            f"向 {target_agent} 交接 {payload_type}：{summary}",
            {"target_agent": target_agent, "payload_type": payload_type},
        )

    def _research_step_outputs(self, step_id: str, state: AdmissionState) -> dict:
        tutors = state.get("tutors", [])
        evidence = state.get("retrieval_evidence", [])
        if step_id == "check_recent_papers":
            return {
                "tutors_with_papers": sum(1 for tutor in tutors if tutor.papers),
                "paper_evidence_count": sum(1 for item in evidence if item.field == "papers"),
            }
        if step_id == "analyze_research_fit":
            return {
                "candidate_count": len(tutors),
                "matched_fields": list(dict.fromkeys(item.field for item in evidence if item.field in {"research_areas", "admission_directions", "summary"})),
            }
        if step_id == "check_admission_status":
            return {
                "admission_evidence_count": sum(1 for item in evidence if item.field in {"admission_directions", "requirements"}),
                "needs_manual_confirmation": True,
            }
        return {}

    def _mark_step(self, state: AdmissionState, agent: str, status: str):
        plan = state.get("plan")
        if not plan:
            return None
        for step in plan.steps:
            if step.agent == agent and step.status in {"pending", "running"}:
                step.status = status
                return step
        return None

    def _mark_step_by_id(self, state: AdmissionState, step_id: str, status: str):
        plan = state.get("plan")
        if not plan:
            return None
        for step in plan.steps:
            if step.id == step_id:
                step.status = status
                return step
        return None
