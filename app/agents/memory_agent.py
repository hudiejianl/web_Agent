from __future__ import annotations

from app.config import get_settings
from app.models.schemas import MemoryState
from app.storage.repositories import MemoryRepository


INTEREST_KEYWORDS = ["人工智能", "机器学习", "深度学习", "大模型", "RAG", "智能体", "自然语言处理", "NLP", "软件工程", "软件安全", "医学影像", "代码智能"]
LOCATION_KEYWORDS = ["北京", "上海", "杭州", "南京", "广州", "深圳", "江浙沪", "浙江", "江苏"]
DEGREE_KEYWORDS = ["硕士", "博士", "直博", "研究生", "保研", "考研"]


class MemoryAgent:
    def __init__(self, repository: MemoryRepository | None = None):
        self.repository = repository or MemoryRepository()
        self.settings = get_settings()

    def load(self, session_id: str) -> MemoryState:
        memory = self.repository.get(session_id)
        memory.recent_messages = self.repository.recent_messages(session_id, self.settings.max_context_messages)
        return memory

    def update(self, session_id: str, user_message: str, assistant_message: str) -> MemoryState:
        memory = self.load(session_id)
        self.repository.append_message(session_id, "user", user_message)
        self.repository.append_message(session_id, "assistant", assistant_message)
        for keyword in INTEREST_KEYWORDS:
            if keyword.lower() in user_message.lower() and keyword not in memory.profile.research_interests:
                memory.profile.research_interests.append(keyword)
        for keyword in LOCATION_KEYWORDS:
            if keyword in user_message and keyword not in memory.profile.preferred_locations:
                memory.profile.preferred_locations.append(keyword)
        for keyword in DEGREE_KEYWORDS:
            if keyword in user_message:
                memory.profile.target_degree = keyword
        memory.recent_messages = self.repository.recent_messages(session_id, self.settings.max_context_messages)
        if len(memory.recent_messages) >= self.settings.summary_trigger_messages:
            memory.summary = self._compress(memory)
        return self.repository.save(memory)

    def _compress(self, memory: MemoryState) -> str:
        interests = "、".join(memory.profile.research_interests) or "未明确"
        locations = "、".join(memory.profile.preferred_locations) or "未明确"
        degree = memory.profile.target_degree or "未明确"
        recent = "；".join(f"{item['role']}：{item['content'][:60]}" for item in memory.recent_messages[-4:])
        return f"用户关注方向：{interests}；地区偏好：{locations}；目标阶段：{degree}。近期对话：{recent}"
