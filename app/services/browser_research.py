from __future__ import annotations

from datetime import datetime
from urllib.parse import quote_plus, urlparse

from app.agents.browser_agent import BrowserAgent, BrowserFetchError
from app.config import get_settings
from app.agents.query_rewriter import DEFAULT_ALLOWED_DOMAINS, QueryRewriter
from app.agents.research_agent import ResearchAgent
from app.models.schemas import AgentTrace, BrowserResearchRequest, BrowserResearchResponse, CandidateLink, TutorProfile
from app.search.result_filter import ResultFilterConfig, SearchResultFilter
from app.services.ingestion import IngestionService
from app.storage.repositories import TraceRepository


# BrowserResearchService 编排“改写搜索词 → 搜索入口 → 导航发现 → 结构化入库”的自主研究流程。
class BrowserResearchService:
    def __init__(
        self,
        browser: BrowserAgent | None = None,
        researcher: ResearchAgent | None = None,
        ingestion: IngestionService | None = None,
        query_rewriter: QueryRewriter | None = None,
    ):
        self.browser = browser or BrowserAgent()
        self.researcher = researcher or ResearchAgent()
        self.ingestion = ingestion or IngestionService()
        self.query_rewriter = query_rewriter or QueryRewriter()
        self.traces = TraceRepository()

    def research(self, request: BrowserResearchRequest) -> BrowserResearchResponse:
        request = self._clamp_request(request)
        trace: list[AgentTrace] = []
        allowed_domains = request.allowed_domains or DEFAULT_ALLOWED_DOMAINS
        rewritten_queries = self.query_rewriter.rewrite(request.query, allowed_domains=allowed_domains, max_queries=request.max_queries)
        trace.append(self._trace("Query Rewriter Agent", "rewrite_search_queries", "completed", f"生成 {len(rewritten_queries)} 条搜索 Query"))
        search_urls = self._build_search_urls(request, rewritten_queries)
        trace.append(self._trace("Planner Agent", "build_search_urls", "completed", f"生成 {len(search_urls)} 个搜索入口"))

        candidates = self._collect_candidates(request, search_urls, rewritten_queries, allowed_domains, trace)
        candidates = self._discover_navigation_candidates(request, candidates, rewritten_queries, allowed_domains, trace)
        tutors = self._browse_and_ingest(request, candidates, trace)
        trace.append(self._trace("Advisor Agent", "summarize_research", "completed", f"筛选 {len(candidates)} 个候选链接，入库 {len(tutors)} 位导师"))
        trace_run = self.traces.save(session_id="browser-research", source="browser_research", trace=trace)
        return BrowserResearchResponse(
            query=request.query,
            trace_id=trace_run.trace_id,
            rewritten_queries=rewritten_queries,
            search_urls=search_urls,
            candidates=candidates,
            tutors=tutors,
            trace=trace,
        )

    def _clamp_request(self, request: BrowserResearchRequest) -> BrowserResearchRequest:
        settings = get_settings()
        return request.model_copy(
            update={
                "max_search_pages": max(1, min(request.max_search_pages, settings.max_browser_search_pages)),
                "max_candidates": max(1, min(request.max_candidates, settings.max_browser_candidates)),
                "max_ingest": max(1, min(request.max_ingest, settings.max_browser_ingest)),
                "max_navigation_pages": max(1, min(request.max_navigation_pages, settings.max_browser_navigation_pages)),
            }
        )

    def _build_search_urls(self, request: BrowserResearchRequest, rewritten_queries: list[str]) -> list[str]:
        urls = [str(url) for url in request.seed_urls]
        pages = max(1, min(request.max_search_pages, 3))
        queries = rewritten_queries or [request.query]
        for query_text in queries:
            for page in range(pages):
                query = quote_plus(query_text)
                if request.search_engine == "baidu":
                    urls.append(f"https://www.baidu.com/s?wd={query}&pn={page * 10}")
                else:
                    offset = page * 10 + 1
                    urls.append(f"https://www.bing.com/search?q={query}&first={offset}")
        return list(dict.fromkeys(urls))

    def _collect_candidates(
        self,
        request: BrowserResearchRequest,
        search_urls: list[str],
        rewritten_queries: list[str],
        allowed_domains: list[str],
        trace: list[AgentTrace],
    ) -> list[CandidateLink]:
        collected: dict[str, CandidateLink] = {}
        result_filter = SearchResultFilter(ResultFilterConfig(allowed_domains=tuple(allowed_domains)))
        filter_query = " ".join([request.query, *rewritten_queries])
        for search_url in search_urls:
            try:
                page = self.browser.fetch(search_url, use_playwright=request.use_playwright, actions=[])
                trace.append(self._trace("Browser Agent", "browse_search_page", "completed", f"已浏览搜索入口：{search_url}"))
            except Exception as exc:
                trace.append(self._trace("Browser Agent", "browse_search_page", "failed", f"搜索入口失败：{search_url}", self._error_metadata(exc)))
                continue
            for candidate in result_filter.filter_links(page.get("links", []), filter_query, search_url):
                self._score_candidate_confidence(candidate)
                existing = collected.get(candidate.url)
                if existing is None or candidate.confidence > existing.confidence:
                    collected[candidate.url] = candidate
        candidates = sorted(collected.values(), key=lambda item: (item.confidence, item.score), reverse=True)
        limited = candidates[: max(1, min(request.max_candidates, 20))]
        trace.append(self._trace("Search Result Filter", "rank_candidate_links", "completed", f"候选链接过滤完成：{len(limited)} / {len(candidates)}"))
        return limited

    def _discover_navigation_candidates(
        self,
        request: BrowserResearchRequest,
        candidates: list[CandidateLink],
        rewritten_queries: list[str],
        allowed_domains: list[str],
        trace: list[AgentTrace],
    ) -> list[CandidateLink]:
        if request.navigation_depth <= 0 or not candidates:
            return candidates
        result_filter = SearchResultFilter(ResultFilterConfig(allowed_domains=tuple(allowed_domains), threshold=4.0))
        filter_query = " ".join([request.query, *rewritten_queries, "导师 教师 个人主页 研究方向"])
        collected = {candidate.url: candidate for candidate in candidates}
        navigation_limit = max(1, min(request.max_navigation_pages, 30))
        navigation_queue = candidates[: max(1, min(navigation_limit, len(candidates)))]
        visited: set[str] = set()
        discovered_count = 0
        pagination_count = 0
        while navigation_queue and len(visited) < navigation_limit:
            page_candidate = navigation_queue.pop(0)
            if page_candidate.url in visited:
                continue
            visited.add(page_candidate.url)
            try:
                page = self.browser.fetch(page_candidate.url, use_playwright=request.use_playwright, actions=[])
                page_candidate.status = "browsed"
                trace.append(self._trace("Browser Agent", "navigate_candidate_page", "completed", f"导航访问候选入口：{page_candidate.url}"))
            except Exception as exc:
                page_candidate.error = str(exc)[:300]
                trace.append(self._trace("Browser Agent", "navigate_candidate_page", "failed", f"导航入口失败：{page_candidate.url}", self._error_metadata(exc)))
                continue
            for pagination in self._pagination_links(page.get("links", []), page_candidate.url):
                if pagination.url not in collected:
                    self._score_candidate_confidence(pagination)
                    collected[pagination.url] = pagination
                    pagination_count += 1
                if pagination.url not in visited and len(visited) + len(navigation_queue) < navigation_limit:
                    navigation_queue.append(pagination)
            for discovered in result_filter.filter_links(page.get("links", []), filter_query, page_candidate.url):
                discovered.score += max(page_candidate.score * 0.2, 1.0)
                self._score_candidate_confidence(discovered)
                if discovered.url not in collected:
                    collected[discovered.url] = discovered
                    discovered_count += 1
        expanded = sorted(collected.values(), key=lambda item: (item.confidence, item.score), reverse=True)[: max(1, min(request.max_candidates, 20))]
        trace.append(self._trace("Browser Agent", "discover_navigation_links", "completed", f"导航式发现新增 {discovered_count} 个候选链接，识别分页 {pagination_count} 个"))
        return expanded

    def _browse_and_ingest(self, request: BrowserResearchRequest, candidates: list[CandidateLink], trace: list[AgentTrace]) -> list[TutorProfile]:
        tutors: list[TutorProfile] = []
        for candidate in candidates[: max(1, min(request.max_ingest, len(candidates) or 1))]:
            try:
                page = self.browser.fetch(candidate.url, use_playwright=request.use_playwright, actions=[])
                candidate.page_quality = self._page_quality(page)
                self._score_candidate_confidence(candidate)
                trace.append(self._trace("Browser Agent", "browse_candidate_page", "completed", f"已打开候选主页：{candidate.url}", {"page_quality": candidate.page_quality, "confidence": candidate.confidence}))
                profile = self.researcher.structure_faculty_page(page)
                profile.homepage = profile.homepage or candidate.url
                saved = self.ingestion.ingest_profile(profile)
                tutors.append(saved)
                candidate.status = "ingested"
                trace.append(self._trace("Research Agent", "structure_and_ingest", "completed", f"已结构化并入库：{saved.name}"))
            except Exception as exc:
                candidate.status = "failed"
                candidate.error = str(exc)[:300]
                trace.append(self._trace("Research Agent", "structure_and_ingest", "failed", f"候选链接处理失败：{candidate.url}", self._error_metadata(exc)))
        for candidate in candidates:
            if candidate.status == "pending":
                candidate.status = "skipped"
        return tutors

    def _pagination_links(self, links: object, source_url: str) -> list[CandidateLink]:
        if not isinstance(links, list):
            return []
        source_host = urlparse(source_url).netloc
        results: list[CandidateLink] = []
        for raw in links:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or "").strip()
            url = str(raw.get("url") or "").strip()
            if not url.startswith("http") or urlparse(url).netloc != source_host:
                continue
            lower = f"{text} {url}".lower()
            if any(token in lower for token in ["下一页", "下页", "next", "page", "p=", "page=", "index_", "list_"]):
                results.append(CandidateLink(text=text[:160], url=url, source_url=source_url, score=6.0, reason="分页链接"))
        return results

    def _page_quality(self, page: dict) -> float:
        text = page.get("text", "") or ""
        links = page.get("links", []) or []
        score = 0.0
        if len(text) >= 300:
            score += 0.25
        if len(text) >= 1000:
            score += 0.2
        if any(keyword in text for keyword in ["研究方向", "招生", "论文", "个人主页", "教授", "导师"]):
            score += 0.25
        if any(keyword in text.lower() for keyword in ["email", "@", "publication", "research"]):
            score += 0.15
        if links:
            score += 0.15
        return round(min(score, 1.0), 4)

    def _score_candidate_confidence(self, candidate: CandidateLink) -> None:
        normalized_score = min(max(candidate.score / 10.0, 0.0), 1.0)
        candidate.confidence = round(min(0.65 * normalized_score + 0.35 * candidate.page_quality, 1.0), 4)

    def _error_metadata(self, exc: Exception) -> dict[str, str | int | float | bool]:
        metadata: dict[str, str | int | float | bool] = {"error": str(exc)[:180], "error_type": type(exc).__name__}
        if isinstance(exc, BrowserFetchError):
            metadata.update({"reason": exc.reason, "attempts": exc.attempts, "url": exc.url})
        return metadata

    def _trace(self, agent: str, action: str, status: str, detail: str, metadata: dict[str, str | int | float | bool] | None = None) -> AgentTrace:
        return AgentTrace(agent=agent, action=action, status=status, detail=detail, timestamp=datetime.utcnow(), metadata=metadata or {})
