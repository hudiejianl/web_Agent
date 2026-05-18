from __future__ import annotations

from app.models.schemas import MemoryState


class ContextCompressor:
    def __init__(self, recent_window: int = 4):
        self.recent_window = max(1, recent_window)

    def compress(self, memory: MemoryState) -> str:
        sections = [
            self._profile_section(memory),
            self._strategy_section(memory),
            self._procedural_section(memory),
            self._event_section(memory),
            self._reflection_section(memory),
            self._recent_section(memory),
        ]
        return "。".join(section for section in sections if section) + "。"

    def _profile_section(self, memory: MemoryState) -> str:
        interests = self._join(memory.profile.research_interests, "未明确")
        locations = self._join(memory.profile.preferred_locations, "未明确")
        degree = memory.profile.target_degree or "未明确"
        return f"用户画像：关注方向={interests}；地区偏好={locations}；目标阶段={degree}"

    def _strategy_section(self, memory: MemoryState) -> str:
        semantic = memory.semantic
        return "申请策略：" + "；".join(
            [
                f"策略={self._join(semantic.application_strategy, '未明确')}",
                f"导师偏好={self._join(semantic.advisor_preferences, '未明确')}",
                f"风险提示={self._join(semantic.risk_flags, '暂无')}",
            ]
        )

    def _procedural_section(self, memory: MemoryState) -> str:
        procedural = memory.procedural
        return "流程偏好：" + "；".join(
            [
                f"执行={self._join(procedural.workflow_preferences, '未明确')}",
                f"材料={self._join(procedural.material_preferences, '未明确')}",
                f"沟通={self._join(procedural.communication_preferences, '未明确')}",
                f"时间={self._join(procedural.scheduling_preferences, '未明确')}",
            ]
        )

    def _event_section(self, memory: MemoryState) -> str:
        events = [f"{event.type}:{event.tutor_name or '未指明'}" for event in memory.episodic_events[-8:]]
        conflicts = [f"{item.field}:{item.previous}->{item.current}" for item in memory.conflicts[-5:]]
        return f"事件记忆：{self._join(events, '暂无')}；冲突处理：{self._join(conflicts, '暂无')}"

    def _reflection_section(self, memory: MemoryState) -> str:
        reflections = [f"{item.topic}:{item.content}" for item in memory.reflections[-6:]]
        return f"长期反思：{self._join(reflections, '暂无')}"

    def _recent_section(self, memory: MemoryState) -> str:
        recent = [f"{item['role']}：{item['content'][:80]}" for item in memory.recent_messages[-self.recent_window :]]
        return f"近期对话窗口：{self._join(recent, '暂无')}"

    def _join(self, items: list[str], default: str) -> str:
        normalized = [item for item in dict.fromkeys(items) if item]
        return "、".join(normalized) if normalized else default
