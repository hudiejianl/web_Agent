from __future__ import annotations

import re

from app.config import get_settings
from app.models.schemas import MemoryEvent, MemoryReflection, MemoryState, RelevantMemory
from app.storage.repositories import MemoryRepository


INTEREST_KEYWORDS = ["人工智能", "机器学习", "深度学习", "大模型", "RAG", "智能体", "多模态", "自然语言处理", "NLP", "软件工程", "软件安全", "医学影像", "代码智能"]
LOCATION_KEYWORDS = ["北京", "上海", "杭州", "南京", "广州", "深圳", "江浙沪", "浙江", "江苏"]
DEGREE_KEYWORDS = ["硕士", "博士", "直博", "研究生", "保研", "考研"]
STRATEGY_KEYWORDS = {
    "顶会论文导向": ["顶会", "论文", "近三年"],
    "企业合作导向": ["企业合作", "产业", "项目合作"],
    "地域优先": ["武汉", "北京", "上海", "江浙沪", "杭州", "南京"],
    "硕博申请准备": ["硕士", "博士", "保研", "考研", "直博"],
}
ADVISOR_PREFERENCE_KEYWORDS = {
    "偏好有招生信息的导师": ["招生", "名额", "招生要求"],
    "偏好主页信息完整的导师": ["主页", "个人主页", "简历"],
    "偏好方向高度匹配的导师": ["匹配", "研究方向", "方向"],
    "偏好已联系或可沟通导师": ["联系", "沟通", "套磁", "发邮件"],
}
RISK_KEYWORDS = {
    "排除用户明确不考虑的导师": ["不要", "不考虑", "排除", "不喜欢", "不合适"],
    "需核实导师最新招生状态": ["不确定", "是否招生", "还招生", "招生状态"],
}
WORKFLOW_PREFERENCE_KEYWORDS = {
    "先筛选导师再准备材料": ["先筛选", "先找导师", "再准备材料"],
    "先查论文和主页再联系": ["先查论文", "先看主页", "再联系"],
    "按优先级分批联系导师": ["分批联系", "按优先级", "优先联系"],
}
MATERIAL_PREFERENCE_KEYWORDS = {
    "偏好邮件模板": ["邮件模板", "套磁信", "邮件"],
    "偏好简历优化": ["简历", "CV", "履历"],
    "偏好研究计划书": ["研究计划", "研究计划书", "proposal"],
}
COMMUNICATION_PREFERENCE_KEYWORDS = {
    "沟通风格偏正式": ["正式", "礼貌", "规范"],
    "希望表达简洁直接": ["简洁", "直接", "短一点"],
    "需要中文沟通材料": ["中文", "中文邮件", "中文材料"],
    "需要英文沟通材料": ["英文", "英文邮件", "英文材料"],
}
SCHEDULING_PREFERENCE_KEYWORDS = {
    "需要申请时间线": ["时间线", "截止日期", "ddl", "deadline"],
    "需要定期跟进": ["定期", "每周", "跟进", "提醒"],
}
EVENT_PATTERNS = {
    "contacted": ["联系", "发邮件", "套磁", "沟通"],
    "favorited": ["收藏", "关注", "感兴趣", "优先考虑"],
    "rejected": ["排除", "不考虑", "不要", "不喜欢", "不合适"],
    "feedback": ["反馈", "回复", "拒绝", "同意", "面试"],
}
TUTOR_NAME_PATTERN = re.compile(r"([一-龥]{2,8})(?:老师|导师|教授)")
CLAUSE_SPLIT_PATTERN = re.compile(r"[，。；;,.！!？?]|但是|另外|并且|同时|但|也")
NAME_PREFIX_WORDS = ["已经", "联系", "发邮件", "套磁", "沟通", "收藏", "关注", "优先考虑", "排除", "不考虑", "不要", "不喜欢", "不合适", "也想", "但", "我", "了", "想"]


class MemoryAgent:
    def __init__(self, repository: MemoryRepository | None = None):
        self.repository = repository or MemoryRepository()
        self.settings = get_settings()

    def load(self, session_id: str) -> MemoryState:
        memory = self.repository.get(session_id)
        memory.recent_messages = self.repository.recent_messages(session_id, self.settings.max_context_messages)
        return memory

    def retrieve_relevant(self, memory: MemoryState, query: str, limit: int = 8) -> list[RelevantMemory]:
        query_terms = self._query_terms(query)
        candidates: list[RelevantMemory] = []
        for item in memory.semantic.research_focus:
            candidates.append(RelevantMemory(type="research_focus", content=item, score=self._memory_score(item, query_terms)))
        for item in memory.semantic.application_strategy:
            candidates.append(RelevantMemory(type="application_strategy", content=item, score=self._memory_score(item, query_terms) + 0.2))
        for item in memory.semantic.advisor_preferences:
            candidates.append(RelevantMemory(type="advisor_preference", content=item, score=self._memory_score(item, query_terms) + 0.2))
        for item in memory.semantic.risk_flags:
            candidates.append(RelevantMemory(type="risk_flag", content=item, score=self._memory_score(item, query_terms) + 0.3))
        for item in [*memory.procedural.workflow_preferences, *memory.procedural.material_preferences, *memory.procedural.communication_preferences, *memory.procedural.scheduling_preferences]:
            candidates.append(RelevantMemory(type="procedural_preference", content=item, score=self._memory_score(item, query_terms) + 0.1))
        for event in memory.episodic_events:
            content = f"{event.type}:{event.tutor_name or '未指明'}:{event.note}"
            candidates.append(RelevantMemory(type="episodic_event", content=content, score=self._memory_score(content, query_terms) + 0.4))
        for reflection in memory.reflections:
            candidates.append(RelevantMemory(type=f"reflection:{reflection.topic}", content=reflection.content, score=self._memory_score(reflection.content, query_terms) + 0.35))
        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        return [item for item in ranked if item.score > 0][:limit]

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
        memory.episodic_events = self._merge_events(memory.episodic_events, self._extract_events(user_message))
        self._update_semantic_memory(memory, user_message)
        self._update_procedural_memory(memory, user_message)
        self._update_reflections(memory)
        memory.recent_messages = self.repository.recent_messages(session_id, self.settings.max_context_messages)
        if len(memory.recent_messages) >= self.settings.summary_trigger_messages:
            memory.summary = self._compress(memory)
        return self.repository.save(memory)

    def _query_terms(self, query: str) -> set[str]:
        terms = {keyword for keyword in [*INTEREST_KEYWORDS, *LOCATION_KEYWORDS, *DEGREE_KEYWORDS] if keyword.lower() in query.lower()}
        terms.update({item for item in re.split(r"\s+|，|。|、", query) if len(item) >= 2})
        return terms

    def _memory_score(self, content: str, query_terms: set[str]) -> float:
        if not query_terms:
            return 0.1
        matched = sum(1 for term in query_terms if term and term.lower() in content.lower())
        return matched / len(query_terms)

    def _update_semantic_memory(self, memory: MemoryState, message: str) -> None:
        memory.semantic.research_focus = self._merge_text_items(memory.semantic.research_focus, memory.profile.research_interests)
        memory.semantic.application_strategy = self._merge_text_items(memory.semantic.application_strategy, self._match_labels(message, STRATEGY_KEYWORDS))
        memory.semantic.advisor_preferences = self._merge_text_items(memory.semantic.advisor_preferences, self._match_labels(message, ADVISOR_PREFERENCE_KEYWORDS))
        memory.semantic.risk_flags = self._merge_text_items(memory.semantic.risk_flags, self._match_labels(message, RISK_KEYWORDS))

    def _update_procedural_memory(self, memory: MemoryState, message: str) -> None:
        memory.procedural.workflow_preferences = self._merge_text_items(memory.procedural.workflow_preferences, self._match_labels(message, WORKFLOW_PREFERENCE_KEYWORDS))
        memory.procedural.material_preferences = self._merge_text_items(memory.procedural.material_preferences, self._match_labels(message, MATERIAL_PREFERENCE_KEYWORDS))
        memory.procedural.communication_preferences = self._merge_text_items(memory.procedural.communication_preferences, self._match_labels(message, COMMUNICATION_PREFERENCE_KEYWORDS))
        memory.procedural.scheduling_preferences = self._merge_text_items(memory.procedural.scheduling_preferences, self._match_labels(message, SCHEDULING_PREFERENCE_KEYWORDS))

    def _update_reflections(self, memory: MemoryState) -> None:
        reflections = list(memory.reflections)
        candidates = [
            self._build_reflection("long_term_goal", [*memory.semantic.research_focus, memory.profile.target_degree or ""]),
            self._build_reflection("strategy", memory.semantic.application_strategy + memory.semantic.advisor_preferences),
            self._build_reflection("workflow", memory.procedural.workflow_preferences + memory.procedural.material_preferences + memory.procedural.communication_preferences + memory.procedural.scheduling_preferences),
            self._build_reflection("risk", memory.semantic.risk_flags),
            self._build_reflection("interaction", [f"{event.type}:{event.tutor_name or '未指明'}" for event in memory.episodic_events[-8:]]),
        ]
        seen = {(item.topic, item.content) for item in reflections}
        for reflection in candidates:
            if reflection and (reflection.topic, reflection.content) not in seen:
                reflections.append(reflection)
                seen.add((reflection.topic, reflection.content))
        memory.reflections = reflections[-20:]

    def _build_reflection(self, topic: str, items: list[str]) -> MemoryReflection | None:
        normalized = [item for item in dict.fromkeys(items) if item]
        if not normalized:
            return None
        content = "、".join(normalized[:8])
        if topic == "long_term_goal":
            content = f"长期目标聚焦于 {content}"
        elif topic == "strategy":
            content = f"申请策略倾向于 {content}"
        elif topic == "workflow":
            content = f"偏好的申请执行方式包括 {content}"
        elif topic == "risk":
            content = f"后续推荐需要注意 {content}"
        elif topic == "interaction":
            content = f"近期导师互动状态包括 {content}"
        return MemoryReflection(topic=topic, content=content)

    def _match_labels(self, message: str, patterns: dict[str, list[str]]) -> list[str]:
        return [label for label, keywords in patterns.items() if any(keyword in message for keyword in keywords)]

    def _merge_text_items(self, existing: list[str], new_items: list[str]) -> list[str]:
        return list(dict.fromkeys([*existing, *new_items]))[-20:]

    def _extract_events(self, message: str) -> list[MemoryEvent]:
        events: list[MemoryEvent] = []
        for clause in CLAUSE_SPLIT_PATTERN.split(message):
            names = [self._clean_tutor_name(name) for name in TUTOR_NAME_PATTERN.findall(clause)] or [""]
            for event_type, keywords in EVENT_PATTERNS.items():
                if any(keyword in clause for keyword in keywords):
                    for name in names:
                        events.append(MemoryEvent(type=event_type, tutor_name=name, note=message[:160]))
        return events

    def _clean_tutor_name(self, name: str) -> str:
        cleaned = name
        changed = True
        while changed:
            changed = False
            for word in NAME_PREFIX_WORDS:
                if cleaned.startswith(word) and len(cleaned) > len(word):
                    cleaned = cleaned[len(word) :]
                    changed = True
        return cleaned[-4:]

    def _merge_events(self, existing: list[MemoryEvent], new_events: list[MemoryEvent]) -> list[MemoryEvent]:
        merged = list(existing)
        seen = {(event.type, event.tutor_name, event.note) for event in merged}
        for event in new_events:
            key = (event.type, event.tutor_name, event.note)
            if key not in seen:
                merged.append(event)
                seen.add(key)
        return merged[-50:]

    def _compress(self, memory: MemoryState) -> str:
        interests = "、".join(memory.profile.research_interests) or "未明确"
        locations = "、".join(memory.profile.preferred_locations) or "未明确"
        degree = memory.profile.target_degree or "未明确"
        events = "；".join(f"{event.type}:{event.tutor_name or '未指明'}" for event in memory.episodic_events[-5:]) or "暂无"
        strategy = "、".join(memory.semantic.application_strategy) or "未明确"
        preferences = "、".join(memory.semantic.advisor_preferences) or "未明确"
        risks = "、".join(memory.semantic.risk_flags) or "暂无"
        workflow = "、".join(memory.procedural.workflow_preferences) or "未明确"
        materials = "、".join(memory.procedural.material_preferences) or "未明确"
        communication = "、".join(memory.procedural.communication_preferences) or "未明确"
        schedule = "、".join(memory.procedural.scheduling_preferences) or "未明确"
        recent = "；".join(f"{item['role']}：{item['content'][:60]}" for item in memory.recent_messages[-4:])
        return f"用户关注方向：{interests}；地区偏好：{locations}；目标阶段：{degree}。申请策略：{strategy}；导师偏好：{preferences}；风险提示：{risks}。流程偏好：{workflow}；材料偏好：{materials}；沟通偏好：{communication}；时间安排：{schedule}。近期事件：{events}。近期对话：{recent}"
