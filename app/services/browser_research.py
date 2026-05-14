from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from urllib.parse import quote_plus, urlparse

from app.agents.browser_agent import BrowserAgent
from app.agents.research_agent import ResearchAgent
from app.models.schemas import AgentTrace, BrowserResearchRequest, BrowserResearchResponse, CandidateLink, TutorProfile
from app.services.ingestion import IngestionService


FACULTY_HINTS = ["导师", "教授", "副教授", "研究员", "faculty", "teacher", "profile", "people", "教师", "师资", "主页", "个人主页"]
REJECT_HINTS = ["login", "signin", "register", "captcha", "javascript:", "mailto:", "#", "招生简章", "新闻", "通知", "招聘"]
ACADEMIC_DOMAINS = [".edu", ".edu.cn", "ac.cn", "cas.cn", "university", "college"]


class BrowserResearchService:
    def __init__(
        self,
        browser: BrowserAgent | None = None,
        researcher: ResearchAgent | None = None,
        ingestion: IngestionService | None = None,
    ):
        self.browser = browser or BrowserAgent()
        self.researcher = researcher or ResearchAgent()
        self.ingestion = ingestion or IngestionService()

    def research(self, request: BrowserResearchRequest) -> BrowserResearchResponse:
        trace: list[AgentTrace] = []
        search_urls = self._build_search_urls(request)
        trace.append(self._trace("Planner Agent", "build_search_urls", "completed", f"生成 {len(search_urls)} 个搜索入口"))

        candidates = self._collect_candidates(request, search_urls, trace)
        tutors = self._browse_and_ingest(request, candidates, trace)
        trace.append(self._trace("Advisor Agent", "summarize_research", "completed", f"筛选 {len(candidates)} 个候选链接，入库 {len(tutors)} 位导师"))
        return BrowserResearchResponse(query=request.query, search_urls=search_urls, candidates=candidates, tutors=tutors, trace=trace)

    def _build_search_urls(self, request: BrowserResearchRequest) -> list[str]:
        urls = [str(url) for url in request.seed_urls]
        pages = max(1, min(request.max_search_pages, 3))
        for page in range(pages):
            query = quote_plus(request.query)
            if request.search_engine == "baidu":
                urls.append(f"https://www.baidu.com/s?wd={query}&pn={page * 10}")
            else:
                offset = page * 10 + 1
                urls.append(f"https://www.bing.com/search?q={query}&first={offset}")
        return list(dict.fromkeys(urls))

    def _collect_candidates(self, request: BrowserResearchRequest, search_urls: list[str], trace: list[AgentTrace]) -> list[CandidateLink]:
        collected: dict[str, CandidateLink] = {}
        for search_url in search_urls:
            try:
                page = self.browser.fetch(search_url, use_playwright=request.use_playwright, actions=[])
                trace.append(self._trace("Browser Agent", "browse_search_page", "completed", f"已浏览搜索入口：{search_url}"))
            except Exception as exc:
                trace.append(self._trace("Browser Agent", "browse_search_page", "failed", f"搜索入口失败：{search_url}", {"error": str(exc)[:180]}))
                continue
            for candidate in self._rank_links(page.get("links", []), request.query, search_url):
                if candidate.url not in collected:
                    collected[candidate.url] = candidate
        candidates = sorted(collected.values(), key=lambda item: item.score, reverse=True)
        limited = candidates[: max(1, min(request.max_candidates, 20))]
        trace.append(self._trace("Research Agent", "rank_candidate_links", "completed", f"候选链接排序完成：{len(limited)} / {len(candidates)}"))
        return limited

    def _rank_links(self, links: object, query: str, source_url: str) -> list[CandidateLink]:
        if not isinstance(links, Iterable):
            return []
        query_terms = [term.lower() for term in query.replace("，", " ").replace("、", " ").split() if term.strip()]
        candidates: list[CandidateLink] = []
        for raw in links:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or "").strip()
            url = str(raw.get("url") or "").strip()
            if not url.startswith("http") or self._is_rejected(url, text):
                continue
            score, reasons = self._score_link(url, text, query_terms)
            if score <= 0:
                continue
            candidates.append(CandidateLink(text=text[:160], url=url, source_url=source_url, score=score, reason="、".join(reasons)))
        return candidates

    def _score_link(self, url: str, text: str, query_terms: list[str]) -> tuple[float, list[str]]:
        lower = f"{url} {text}".lower()
        score = 0.0
        reasons: list[str] = []
        for hint in FACULTY_HINTS:
            if hint.lower() in lower:
                score += 2.0
                reasons.append(f"包含{hint}")
                break
        for domain in ACADEMIC_DOMAINS:
            if domain in lower:
                score += 1.5
                reasons.append("高校/科研域名")
                break
        matched_terms = [term for term in query_terms if term and term in lower]
        if matched_terms:
            score += min(len(matched_terms), 4) * 0.8
            reasons.append("匹配查询词")
        path = urlparse(url).path.lower()
        if any(token in path for token in ["teacher", "faculty", "people", "profile", "staff", "person", "teacherinfo"]):
            score += 1.5
            reasons.append("疑似个人主页路径")
        return score, reasons

    def _is_rejected(self, url: str, text: str) -> bool:
        lower = f"{url} {text}".lower()
        return any(hint in lower for hint in REJECT_HINTS)

    def _browse_and_ingest(self, request: BrowserResearchRequest, candidates: list[CandidateLink], trace: list[AgentTrace]) -> list[TutorProfile]:
        tutors: list[TutorProfile] = []
        for candidate in candidates[: max(1, min(request.max_ingest, len(candidates) or 1))]:
            try:
                page = self.browser.fetch(candidate.url, use_playwright=request.use_playwright, actions=[])
                trace.append(self._trace("Browser Agent", "browse_candidate_page", "completed", f"已打开候选主页：{candidate.url}"))
                profile = self.researcher.structure_faculty_page(page)
                profile.homepage = profile.homepage or candidate.url
                saved = self.ingestion.ingest_profile(profile)
                tutors.append(saved)
                candidate.status = "ingested"
                trace.append(self._trace("Research Agent", "structure_and_ingest", "completed", f"已结构化并入库：{saved.name}"))
            except Exception as exc:
                candidate.status = "failed"
                candidate.error = str(exc)[:300]
                trace.append(self._trace("Research Agent", "structure_and_ingest", "failed", f"候选链接处理失败：{candidate.url}", {"error": candidate.error}))
        for candidate in candidates:
            if candidate.status == "pending":
                candidate.status = "skipped"
        return tutors

    def _trace(self, agent: str, action: str, status: str, detail: str, metadata: dict[str, str | int | float | bool] | None = None) -> AgentTrace:
        return AgentTrace(agent=agent, action=action, status=status, detail=detail, timestamp=datetime.utcnow(), metadata=metadata or {})
