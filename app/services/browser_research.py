from __future__ import annotations

from datetime import datetime
from urllib.parse import quote_plus

from app.agents.browser_agent import BrowserAgent
from app.agents.query_rewriter import DEFAULT_ALLOWED_DOMAINS, QueryRewriter
from app.agents.research_agent import ResearchAgent
from app.models.schemas import AgentTrace, BrowserResearchRequest, BrowserResearchResponse, CandidateLink, TutorProfile
from app.search.result_filter import ResultFilterConfig, SearchResultFilter
from app.services.ingestion import IngestionService


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

    def research(self, request: BrowserResearchRequest) -> BrowserResearchResponse:
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
        return BrowserResearchResponse(query=request.query, rewritten_queries=rewritten_queries, search_urls=search_urls, candidates=candidates, tutors=tutors, trace=trace)

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
                trace.append(self._trace("Browser Agent", "browse_search_page", "failed", f"搜索入口失败：{search_url}", {"error": str(exc)[:180]}))
                continue
            for candidate in result_filter.filter_links(page.get("links", []), filter_query, search_url):
                existing = collected.get(candidate.url)
                if existing is None or candidate.score > existing.score:
                    collected[candidate.url] = candidate
        candidates = sorted(collected.values(), key=lambda item: item.score, reverse=True)
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
        navigation_pages = candidates[: max(1, min(request.max_navigation_pages, len(candidates)))]
        discovered_count = 0
        for page_candidate in navigation_pages:
            try:
                page = self.browser.fetch(page_candidate.url, use_playwright=request.use_playwright, actions=[])
                page_candidate.status = "browsed"
                trace.append(self._trace("Browser Agent", "navigate_candidate_page", "completed", f"导航访问候选入口：{page_candidate.url}"))
            except Exception as exc:
                page_candidate.error = str(exc)[:300]
                trace.append(self._trace("Browser Agent", "navigate_candidate_page", "failed", f"导航入口失败：{page_candidate.url}", {"error": page_candidate.error}))
                continue
            for discovered in result_filter.filter_links(page.get("links", []), filter_query, page_candidate.url):
                discovered.score += max(page_candidate.score * 0.2, 1.0)
                if discovered.url not in collected:
                    collected[discovered.url] = discovered
                    discovered_count += 1
        expanded = sorted(collected.values(), key=lambda item: item.score, reverse=True)[: max(1, min(request.max_candidates, 20))]
        trace.append(self._trace("Browser Agent", "discover_navigation_links", "completed", f"导航式发现新增 {discovered_count} 个候选链接"))
        return expanded

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
