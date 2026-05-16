from __future__ import annotations

import re

from app.models.schemas import AgentPlan, PlanStep, TaskType


URL_PATTERN = re.compile(r"https?://[^\s，。)）]+")


class PlannerAgent:
    def plan(self, message: str, previous_plan_id: str | None = None, previous_constraints: list[str] | None = None) -> AgentPlan:
        previous_constraints = previous_constraints or []
        urls = URL_PATTERN.findall(message)
        lowered = message.lower()
        task_type = TaskType.chat
        if urls or "采集" in message or "主页" in message:
            task_type = TaskType.ingest_url if urls else TaskType.search_tutors
        if "比较" in message or "对比" in message:
            task_type = TaskType.compare_tutors

        constraints = list(dict.fromkeys([*previous_constraints, *self._extract_constraints(message)]))
        is_replan = bool(previous_plan_id and self._is_constraint_update(message))
        steps = [
            PlanStep(
                id="understand_goal",
                name="重新理解申请目标与补充约束" if is_replan else "理解申请目标与约束",
                agent="Planner Agent",
                status="completed",
                rationale="合并历史计划约束和用户新增约束" if is_replan else "识别研究方向、地区、学位阶段、论文和合作等筛选条件",
                inputs={"message": message, "previous_plan_id": previous_plan_id or ""},
                outputs={"constraints": constraints, "urls": urls, "is_replan": is_replan},
                expected_output="结构化申请目标",
            )
        ]
        previous_step = "understand_goal"
        if urls:
            steps.append(
                PlanStep(
                    id="ingest_urls",
                    name="浏览并采集导师网页",
                    agent="Browser Agent",
                    depends_on=[previous_step],
                    rationale="从用户给定网页提取正文、链接和导师主页证据，并写入知识库",
                    inputs={"urls": urls},
                    expected_output="网页正文与结构化导师档案",
                )
            )
            previous_step = "ingest_urls"
        if self._needs_external_research(message):
            steps.append(
                PlanStep(
                    id="plan_external_research",
                    name="规划外部网页调研",
                    agent="Planner Agent",
                    depends_on=[previous_step],
                    rationale="用户提出了地区、近三年论文、企业合作等复合约束，需要后续 Browser Agent 扩展搜索",
                    inputs={"constraints": constraints},
                    expected_output="待搜索高校、导师主页和论文线索",
                )
            )
            previous_step = "plan_external_research"
        steps.extend(
            [
                PlanStep(
                    id="retrieve_tutors",
                    name="检索本地导师知识库",
                    agent="RAG Retriever",
                    depends_on=[previous_step],
                    rationale="从已入库导师档案中召回候选人",
                    inputs={"query": message, "constraints": constraints},
                    expected_output="候选导师列表与证据片段",
                ),
                PlanStep(
                    id="analyze_candidates",
                    name="分析候选导师匹配度",
                    agent="Research Agent",
                    depends_on=["retrieve_tutors"],
                    rationale="检查方向、论文、招生要求和用户长期偏好的匹配程度",
                    expected_output="导师匹配理由与风险点",
                ),
                PlanStep(
                    id="generate_advice",
                    name="生成个性化升学建议",
                    agent="Advisor Agent",
                    depends_on=["analyze_candidates"],
                    rationale="基于候选导师、证据和记忆给出排序建议",
                    expected_output="带证据的推荐结果和下一步行动",
                ),
            ]
        )

        return AgentPlan(
            task_type=task_type,
            objective=message,
            constraints=constraints,
            steps=steps,
            need_retrieval=True,
            need_ingestion=bool(urls),
            urls=urls,
            is_replan=is_replan,
            replan_from=previous_plan_id if is_replan else None,
        )

    def _extract_constraints(self, message: str) -> list[str]:
        constraints = []
        for keyword in ["武汉", "北京", "上海", "杭州", "南京", "江浙沪", "多模态", "人工智能", "RAG", "大模型", "顶会", "近三年", "企业合作", "硕士", "博士"]:
            if keyword.lower() in message.lower():
                constraints.append(keyword)
        return constraints

    def _needs_external_research(self, message: str) -> bool:
        return any(keyword in message for keyword in ["近三年", "顶会", "企业合作", "武汉", "高校", "主页", "论文"])

    def _is_constraint_update(self, message: str) -> bool:
        return any(keyword in message for keyword in ["再", "另外", "补充", "改成", "换成", "优先", "不要", "同时", "还要", "限定"])
