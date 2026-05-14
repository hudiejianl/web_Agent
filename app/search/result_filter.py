from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

from app.models.schemas import CandidateLink


POSITIVE_FEATURES = {
    "edu.cn": 5.0,
    "ac.cn": 4.0,
    "导师": 4.0,
    "教师": 4.0,
    "教授": 4.0,
    "个人主页": 4.0,
    "研究方向": 4.0,
    "招生": 3.0,
    "计算机学院": 3.0,
    "人工智能": 2.0,
    "多模态": 2.0,
    "大模型": 2.0,
    "faculty": 4.0,
    "teacher": 4.0,
    "profile": 3.0,
    "people": 2.0,
    "师资队伍": 4.0,
    "师资力量": 4.0,
    "教师队伍": 4.0,
    "教师名录": 4.0,
    "faculty list": 4.0,
}
NEGATIVE_FEATURES = {
    "旅游": -10.0,
    "酒店": -10.0,
    "广告": -8.0,
    "新闻": -4.0,
    "招聘": -4.0,
    "采购": -5.0,
    "login": -6.0,
    "signin": -6.0,
    "captcha": -10.0,
    "javascript:": -10.0,
    "mailto:": -10.0,
}
ACADEMIC_PATH_HINTS = ["teacher", "faculty", "people", "profile", "staff", "person", "teacherinfo", "tutor", "szdw", "szll", "teachers"]


@dataclass(frozen=True)
class ResultFilterConfig:
    allowed_domains: tuple[str, ...] = ("edu.cn", "hust.edu.cn", "whut.edu.cn", "wdu.edu.cn")
    threshold: float = 5.0


class SearchResultFilter:
    def __init__(self, config: ResultFilterConfig | None = None):
        self.config = config or ResultFilterConfig()

    def filter_links(self, links: object, query: str, source_url: str) -> list[CandidateLink]:
        if not isinstance(links, Iterable):
            return []
        candidates = [candidate for candidate in self._score_links(links, query, source_url) if candidate.score >= self.config.threshold]
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def _score_links(self, links: Iterable[object], query: str, source_url: str) -> list[CandidateLink]:
        query_terms = [term.lower() for term in query.replace("，", " ").replace("、", " ").split() if term.strip()]
        candidates: list[CandidateLink] = []
        for raw in links:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or "").strip()
            url = str(raw.get("url") or "").strip()
            if not url.startswith("http"):
                continue
            score, reasons = self.score(url, text, query_terms)
            candidates.append(CandidateLink(text=text[:160], url=url, source_url=source_url, score=score, reason="、".join(reasons)))
        return candidates

    def score(self, url: str, text: str, query_terms: list[str] | None = None) -> tuple[float, list[str]]:
        query_terms = query_terms or []
        lower = f"{url} {text}".lower()
        score = 0.0
        reasons: list[str] = []
        for domain in self.config.allowed_domains:
            if domain.lower() in lower:
                score += 5.0
                reasons.append(f"允许域名:{domain}")
                break
        for feature, weight in POSITIVE_FEATURES.items():
            if feature.lower() in lower:
                score += weight
                reasons.append(feature)
        for feature, weight in NEGATIVE_FEATURES.items():
            if feature.lower() in lower:
                score += weight
                reasons.append(feature)
        matched_terms = [term for term in query_terms if term and term in lower]
        if matched_terms:
            score += min(len(matched_terms), 5) * 0.8
            reasons.append("匹配查询词")
        path = urlparse(url).path.lower()
        if any(token in path for token in ACADEMIC_PATH_HINTS):
            score += 2.5
            reasons.append("疑似教师主页路径")
        return score, reasons
