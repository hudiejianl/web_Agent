from __future__ import annotations

from app.llm.provider import LLMResult, get_llm_client
from app.models.schemas import AgentPlan, MemoryState, TutorProfile


class AdvisorAgent:
    def answer(self, message: str, tutors: list[TutorProfile], memory: MemoryState, plan: AgentPlan | None = None) -> tuple[str, LLMResult]:
        llm_result = self._llm_answer(message, tutors, memory, plan)
        if llm_result.content:
            return llm_result.content, llm_result
        return self._rule_answer(message, tutors, memory), llm_result

    def _rule_answer(self, message: str, tutors: list[TutorProfile], memory: MemoryState) -> str:
        if not tutors:
            return (
                "我还没有检索到足够匹配的导师资料。你可以提供导师主页 URL，或补充目标方向、学校层次、地区偏好，"
                "系统会先采集资料再做结构化分析和推荐。"
            )

        profile = memory.profile
        lines = ["根据当前知识库和你的偏好，我建议优先关注以下导师："]
        for index, tutor in enumerate(tutors[:5], start=1):
            areas = "、".join(tutor.research_areas) or "未标注"
            directions = "、".join(tutor.admission_directions) or "未标注"
            evidence = tutor.evidence[0].snippet if tutor.evidence else tutor.summary
            lines.extend(
                [
                    f"\n{index}. {tutor.name}（{tutor.institution}，{tutor.title or '导师'}）",
                    f"   - 匹配点：研究方向包括 {areas}；招生方向包括 {directions}。",
                    f"   - 适合原因：与你提到的 {self._preference_text(profile)} 有关联。",
                    f"   - 证据：{evidence}",
                ]
            )
        lines.append("\n下一步建议：确认目标院校层次、准备套磁邮件，并逐一核对导师主页的最新招生状态。")
        return "\n".join(lines)

    def _llm_answer(self, message: str, tutors: list[TutorProfile], memory: MemoryState, plan: AgentPlan | None) -> LLMResult:
        if not tutors:
            return get_llm_client().complete(
                system="你是一个升学规划 Research Agent。回答必须诚实说明当前资料不足，并给出下一步采集信息建议。",
                user=f"用户问题：{message}\n用户画像：{memory.profile.model_dump()}",
                max_tokens=700,
            )
        tutor_payload = [
            {
                "name": tutor.name,
                "title": tutor.title,
                "institution": tutor.institution,
                "department": tutor.department,
                "location": tutor.location,
                "research_areas": tutor.research_areas,
                "admission_directions": tutor.admission_directions,
                "requirements": tutor.requirements,
                "papers": [paper.model_dump() for paper in tutor.papers[:5]],
                "summary": tutor.summary,
                "evidence": [item.model_dump() for item in tutor.evidence[:3]],
            }
            for tutor in tutors[:5]
        ]
        plan_payload = plan.model_dump() if plan else {}
        system = (
            "你是一个严谨的升学 Research Agent，负责根据用户画像、任务计划、导师候选和证据生成个性化导师推荐。"
            "必须基于给定证据回答，不要编造导师信息。输出中文，结构包括：推荐排序、匹配理由、风险点、下一步行动。"
        )
        user = (
            f"用户问题：{message}\n"
            f"用户画像：{memory.profile.model_dump()}\n"
            f"任务计划：{plan_payload}\n"
            f"候选导师资料：{tutor_payload}"
        )
        return get_llm_client().complete(system=system, user=user, max_tokens=1400)

    def _preference_text(self, memory: object) -> str:
        interests = getattr(memory, "research_interests", []) or ["研究兴趣"]
        locations = getattr(memory, "preferred_locations", [])
        degree = getattr(memory, "target_degree", None)
        parts = ["、".join(interests)]
        if locations:
            parts.append("地区偏好：" + "、".join(locations))
        if degree:
            parts.append("目标阶段：" + degree)
        return "；".join(parts)
