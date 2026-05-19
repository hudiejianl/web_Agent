from __future__ import annotations

from collections import Counter
from datetime import datetime
from urllib.parse import quote_plus, urlparse

from app.agents.browser_agent import BrowserAgent, BrowserFetchError
from app.config import get_settings
from app.agents.query_rewriter import DEFAULT_ALLOWED_DOMAINS, QueryRewriter
from app.agents.research_agent import ResearchAgent
from app.models.schemas import AgentTrace, BrowserResearchQualityReport, BrowserResearchRequest, BrowserResearchResponse, CandidateLink, TutorProfile
from app.search.result_filter import ResultFilterConfig, SearchResultFilter
from app.services.ingestion import IngestionService
from app.services.seed_sites import UniversitySeedSiteService
from app.storage.repositories import TraceRepository


# BrowserResearchService 编排“改写搜索词 → 搜索入口 → 导航发现 → 结构化入库”的自主研究流程。
class BrowserResearchService:
    def __init__(
        self,
        browser: BrowserAgent | None = None,
        researcher: ResearchAgent | None = None,
        ingestion: IngestionService | None = None,
        query_rewriter: QueryRewriter | None = None,
        seed_sites: UniversitySeedSiteService | None = None,
    ):
        self.browser = browser or BrowserAgent()
        self.researcher = researcher or ResearchAgent()
        self.ingestion = ingestion or IngestionService()
        self.query_rewriter = query_rewriter or QueryRewriter()
        self.seed_sites = seed_sites or UniversitySeedSiteService()
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
        quality_report = self._build_quality_report(candidates, len(tutors))
        summary_action = "预检" if request.dry_run else "入库"
        trace.append(self._trace("Advisor Agent", "summarize_research", "completed", f"筛选 {quality_report.total_candidates} 个候选链接，合格 {quality_report.eligible_candidates} 个，{summary_action} {len(tutors)} 位导师", {"eligible_candidates": quality_report.eligible_candidates, "average_profile_quality_score": quality_report.average_profile_quality_score}))
        trace_run = self.traces.save(session_id="browser-research", source="browser_research", trace=trace)
        return BrowserResearchResponse(
            query=request.query,
            dry_run=request.dry_run,
            trace_id=trace_run.trace_id,
            rewritten_queries=rewritten_queries,
            search_urls=search_urls,
            candidates=candidates,
            tutors=tutors,
            quality_report=quality_report,
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
        if not urls:
            urls.extend(self.seed_sites.seed_urls_for_query(request.query, limit=request.max_search_pages))
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
        filter_query = " ".join([request.query, *rewritten_queries, "大学 学院 师资 导师 教师 个人主页 论文 研究方向"])
        for candidate in candidates:
            candidate.link_type = self._navigation_link_type(candidate.url, candidate.text)
            candidate.depth = 0
        collected = {candidate.url: candidate for candidate in candidates}
        navigation_limit = max(1, min(request.max_navigation_pages, 30))
        navigation_queue = candidates[: max(1, min(navigation_limit, len(candidates)))]
        visited: set[str] = set()
        discovered_count = 0
        pagination_count = 0
        deep_count = 0
        while navigation_queue and len(visited) < navigation_limit:
            page_candidate = navigation_queue.pop(0)
            if page_candidate.url in visited:
                continue
            visited.add(page_candidate.url)
            try:
                page = self.browser.fetch(page_candidate.url, use_playwright=request.use_playwright, actions=[])
                page_candidate.status = "browsed"
                page_candidate.page_quality = self._page_quality(page)
                self._score_candidate_confidence(page_candidate)
                trace.append(self._trace("Browser Agent", "navigate_candidate_page", "completed", f"导航访问候选入口：{page_candidate.url}"))
            except Exception as exc:
                page_candidate.error = str(exc)[:300]
                trace.append(self._trace("Browser Agent", "navigate_candidate_page", "failed", f"导航入口失败：{page_candidate.url}", self._error_metadata(exc)))
                continue
            for pagination in self._pagination_links(page.get("links", []), page_candidate.url):
                pagination.depth = page_candidate.depth
                if pagination.url not in collected:
                    self._score_candidate_confidence(pagination)
                    collected[pagination.url] = pagination
                    pagination_count += 1
                if self._should_follow_navigation(pagination, request.navigation_depth) and pagination.url not in visited and len(visited) + len(navigation_queue) < navigation_limit:
                    navigation_queue.append(pagination)
            for discovered in result_filter.filter_links(page.get("links", []), filter_query, page_candidate.url):
                discovered.score += max(page_candidate.score * 0.2, 1.0)
                discovered.link_type = self._navigation_link_type(discovered.url, discovered.text)
                discovered.depth = page_candidate.depth + 1
                self._score_candidate_confidence(discovered)
                if discovered.url not in collected:
                    collected[discovered.url] = discovered
                    discovered_count += 1
                if self._should_follow_navigation(discovered, request.navigation_depth) and discovered.url not in visited and len(visited) + len(navigation_queue) < navigation_limit:
                    navigation_queue.append(discovered)
            for deep_link in self._deep_navigation_links(page.get("links", []), page_candidate.url, allowed_domains, page_candidate.depth):
                if deep_link.url not in collected:
                    self._score_candidate_confidence(deep_link)
                    collected[deep_link.url] = deep_link
                    deep_count += 1
                else:
                    existing = collected[deep_link.url]
                    if deep_link.score > existing.score:
                        existing.score = deep_link.score
                        existing.reason = deep_link.reason
                        existing.link_type = deep_link.link_type
                        existing.depth = min(existing.depth, deep_link.depth)
                        self._score_candidate_confidence(existing)
                    deep_link = existing
                if self._should_follow_navigation(deep_link, request.navigation_depth) and deep_link.url not in visited and len(visited) + len(navigation_queue) < navigation_limit:
                    navigation_queue.append(deep_link)
        expanded = sorted(collected.values(), key=lambda item: (item.confidence, item.score), reverse=True)[: max(1, min(request.max_candidates, 20))]
        trace.append(self._trace("Browser Agent", "discover_navigation_links", "completed", f"导航式发现新增 {discovered_count} 个候选链接，识别分页 {pagination_count} 个，深链路 {deep_count} 个"))
        return expanded

    def _browse_and_ingest(self, request: BrowserResearchRequest, candidates: list[CandidateLink], trace: list[AgentTrace]) -> list[TutorProfile]:
        tutors: list[TutorProfile] = []
        ingest_attempts = 0
        max_ingest = max(1, min(request.max_ingest, len(candidates) or 1))
        for candidate in candidates:
            precheck_reasons = self._candidate_precheck_reasons(candidate)
            if precheck_reasons:
                self._mark_candidate_rejected(candidate, precheck_reasons, "skipped")
                trace.append(self._trace("Research Agent", "precheck_candidate", "skipped", f"候选链接暂不入库：{candidate.url}，原因：{'；'.join(precheck_reasons)}", self._quality_metadata(candidate)))
                continue
            if ingest_attempts >= max_ingest:
                self._mark_candidate_rejected(candidate, ["超过本次入库数量上限"], "skipped")
                continue
            ingest_attempts += 1
            try:
                page = self.browser.fetch(candidate.url, use_playwright=request.use_playwright, actions=[])
                candidate.page_quality = self._page_quality(page)
                self._score_candidate_confidence(candidate)
                trace.append(self._trace("Browser Agent", "browse_candidate_page", "completed", f"已打开候选主页：{candidate.url}", {"page_quality": candidate.page_quality, "confidence": candidate.confidence}))
                profile = self.researcher.structure_faculty_page(page)
                profile.homepage = profile.homepage or candidate.url
                self._score_profile_quality(profile, candidate, page)
                if not candidate.ingest_eligible:
                    candidate.status = "failed"
                    candidate.error = "；".join(candidate.quality_reasons)
                    trace.append(self._trace("Research Agent", "validate_profile_quality", "failed", f"候选档案未入库：{candidate.url}，质量分 {candidate.profile_quality_score}，原因：{candidate.error}", self._quality_metadata(candidate)))
                    continue
                if request.dry_run:
                    tutors.append(profile)
                    candidate.status = "browsed"
                    trace.append(self._trace("Research Agent", "preview_profile_quality", "completed", f"预检通过但未写库：{profile.name}，质量分 {candidate.profile_quality_score}", self._quality_metadata(candidate)))
                    continue
                saved = self.ingestion.ingest_profile(profile)
                tutors.append(saved)
                candidate.status = "ingested"
                trace.append(self._trace("Research Agent", "structure_and_ingest", "completed", f"已结构化并入库：{saved.name}，质量分 {candidate.profile_quality_score}", self._quality_metadata(candidate)))
            except Exception as exc:
                candidate.status = "failed"
                candidate.error = str(exc)[:300]
                trace.append(self._trace("Research Agent", "structure_and_ingest", "failed", f"候选链接处理失败：{candidate.url}", self._error_metadata(exc)))
        for candidate in candidates:
            if candidate.status == "pending":
                self._mark_candidate_rejected(candidate, ["未进入本轮入库处理"], "skipped")
        return tutors

    def _build_quality_report(self, candidates: list[CandidateLink], tutor_count: int) -> BrowserResearchQualityReport:
        total = len(candidates)
        eligible = sum(1 for candidate in candidates if candidate.ingest_eligible)
        rejected = total - eligible
        profile_scores = [candidate.profile_quality_score for candidate in candidates]
        page_scores = [candidate.page_quality for candidate in candidates]
        rejection_reasons = Counter(reason for candidate in candidates if not candidate.ingest_eligible for reason in (candidate.quality_reasons or ([candidate.error] if candidate.error else ["未说明"])))
        top_candidates = sorted(candidates, key=lambda candidate: (candidate.profile_quality_score, candidate.confidence, candidate.score), reverse=True)[:5]
        return BrowserResearchQualityReport(
            total_candidates=total,
            eligible_candidates=eligible,
            rejected_candidates=rejected,
            ingested_or_previewed_tutors=tutor_count,
            average_profile_quality_score=round(sum(profile_scores) / total, 4) if total else 0.0,
            average_page_quality=round(sum(page_scores) / total, 4) if total else 0.0,
            status_counts=dict(Counter(candidate.status for candidate in candidates)),
            link_type_counts=dict(Counter(candidate.link_type for candidate in candidates)),
            rejection_reasons=dict(rejection_reasons.most_common()),
            top_candidates=top_candidates,
        )

    def _candidate_precheck_reasons(self, candidate: CandidateLink) -> list[str]:
        url = candidate.url.lower()
        host = urlparse(url).netloc.lower()
        reasons: list[str] = []
        if any(domain in host for domain in ["bing.com", "baidu.com", "sogou.com", "so.com"]) or "/search?" in url:
            reasons.append("搜索结果页不能作为导师主页")
        if host.endswith("gov.cn") or "baike.baidu.com" in host:
            reasons.append("非导师主页来源")
        if candidate.link_type in {"school", "college", "faculty_list", "pagination", "paper"}:
            reasons.append(f"{candidate.link_type} 链接只用于导航发现，不直接入库")
        if any(token in url for token in ["login", "signin", "captcha"]):
            reasons.append("登录或验证码页面不采集")
        return reasons

    def _mark_candidate_rejected(self, candidate: CandidateLink, reasons: list[str], status: str = "failed") -> None:
        candidate.status = status
        candidate.ingest_eligible = False
        candidate.quality_reasons = reasons
        candidate.profile_quality_score = 0.0
        candidate.error = "；".join(reasons)

    def _score_profile_quality(self, profile: TutorProfile, candidate: CandidateLink, page: dict) -> None:
        url = (profile.homepage or candidate.url or "").lower()
        host = urlparse(url).netloc.lower()
        name = (profile.name or "").strip()
        text = f"{page.get('title') or ''} {page.get('text') or ''}"
        lower_text = text.lower()
        invalid_names = {"未知导师", "导师", "教师", "教授", "副教授", "讲师", "研究员", "特聘", "女副", "武汉市", "Professor", "Unknown"}
        hard_reasons: list[str] = []
        positive_reasons: list[str] = []
        score = 0.0

        if any(domain in host for domain in ["bing.com", "baidu.com", "sogou.com", "so.com"]) or "/search?" in url:
            hard_reasons.append("搜索结果页不能作为导师主页")
        if host.endswith("gov.cn") or "baike.baidu.com" in host:
            hard_reasons.append("非导师主页来源")
        if not name or name in invalid_names or len(name) > 12:
            hard_reasons.append("导师姓名不可信")
        elif any(token in name.lower() for token in ["site:", "http", "www", "search", "bing", "baidu"]) or any(token in name for token in ["æ", "å", "�"]):
            hard_reasons.append("导师姓名疑似噪声")
        else:
            score += 0.25
            positive_reasons.append("姓名可信")

        has_profile_context = candidate.link_type == "profile" or any(token in url for token in ["teacher", "tutor", "profile", "person", "teacherinfo"]) or any(token in text for token in ["个人主页", "教师简介", "导师简介", "研究方向"])
        if has_profile_context:
            score += 0.2
            positive_reasons.append("页面具备导师主页语境")
        else:
            hard_reasons.append("页面不像导师个人主页")

        if profile.institution and profile.institution != "未知机构":
            score += 0.15
            positive_reasons.append("机构可信")
        elif profile.department:
            score += 0.1
            positive_reasons.append("院系可信")
        else:
            hard_reasons.append("缺少可信机构或院系")

        evidence_score = 0.0
        if profile.research_areas:
            evidence_score += 0.18
            positive_reasons.append("识别到研究方向")
        if profile.email:
            evidence_score += 0.08
            positive_reasons.append("识别到邮箱")
        if profile.papers:
            evidence_score += 0.09
            positive_reasons.append("识别到论文线索")
        if evidence_score == 0:
            hard_reasons.append("缺少研究方向、邮箱或论文证据")
        score += evidence_score

        if any(token in lower_text for token in ["登录", "验证码", "captcha", "hotel", "旅游", "新闻", "百度", "bing", "无法访问", "404", "403"]):
            hard_reasons.append("页面包含明显噪声或不可访问提示")

        score += min(candidate.page_quality * 0.17, 0.17)
        candidate.profile_quality_score = round(min(score, 1.0), 4)
        candidate.quality_reasons = hard_reasons or positive_reasons
        candidate.ingest_eligible = not hard_reasons and candidate.profile_quality_score >= 0.55
        if not candidate.ingest_eligible and not hard_reasons:
            candidate.quality_reasons = [*positive_reasons, "质量分低于入库阈值"]

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
                results.append(CandidateLink(text=text[:160], url=url, source_url=source_url, score=6.0, reason="分页链接", link_type="pagination"))
        return results

    def _deep_navigation_links(self, links: object, source_url: str, allowed_domains: list[str], source_depth: int) -> list[CandidateLink]:
        if not isinstance(links, list):
            return []
        source_host = urlparse(source_url).netloc.lower()
        allowed = [domain.lower() for domain in allowed_domains]
        results: list[CandidateLink] = []
        for raw in links:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or "").strip()
            url = str(raw.get("url") or "").strip()
            if not url.startswith("http"):
                continue
            host = urlparse(url).netloc.lower()
            lower = f"{text} {url}".lower()
            if any(token in lower for token in ["login", "signin", "captcha", "javascript:", "mailto:", "登录", "验证码"]):
                continue
            if host != source_host and not any(domain in host for domain in allowed):
                continue
            link_type = self._navigation_link_type(url, text)
            if link_type == "other":
                continue
            score = {
                "school": 5.0,
                "college": 6.0,
                "faculty_list": 8.0,
                "profile": 9.0,
                "paper": 7.0,
                "pagination": 6.0,
            }.get(link_type, 4.0)
            if host == source_host:
                score += 1.0
            results.append(CandidateLink(text=text[:160], url=url, source_url=source_url, score=score, reason=f"深链路:{link_type}", link_type=link_type, depth=source_depth + 1))
        return sorted(results, key=lambda item: item.score, reverse=True)

    def _navigation_link_type(self, url: str, text: str) -> str:
        lower = f"{text} {url}".lower()
        if any(token in lower for token in ["下一页", "下页", "next", "page=", "p=", "index_", "list_"]):
            return "pagination"
        if any(token in lower for token in ["publication", "publications", "paper", "papers", "pubs", "论文", "科研成果", "学术成果", "代表论文"]):
            return "paper"
        if any(token in lower for token in ["个人主页", "教师简介", "个人简介", "导师简介", "profile", "teacherinfo", "person", "tutor"]):
            return "profile"
        if any(token in lower for token in ["teacher", "faculty", "staff", "people", "师资队伍", "师资力量", "教师队伍", "教师名录", "导师队伍"]):
            return "faculty_list"
        if any(token in lower for token in ["学院", "院系", "系", "college", "school", "department", "计算机", "人工智能"]):
            return "college"
        if any(token in lower for token in ["大学", "university", "edu.cn"]):
            return "school"
        return "other"

    def _should_follow_navigation(self, candidate: CandidateLink, navigation_depth: int) -> bool:
        if candidate.depth > navigation_depth:
            return False
        return candidate.link_type in {"school", "college", "faculty_list", "pagination", "profile"}

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

    def _quality_metadata(self, candidate: CandidateLink) -> dict[str, str | int | float | bool]:
        return {
            "profile_quality_score": candidate.profile_quality_score,
            "ingest_eligible": candidate.ingest_eligible,
            "quality_reasons": "；".join(candidate.quality_reasons),
            "link_type": candidate.link_type,
            "confidence": candidate.confidence,
        }

    def _error_metadata(self, exc: Exception) -> dict[str, str | int | float | bool]:
        metadata: dict[str, str | int | float | bool] = {"error": str(exc)[:180], "error_type": type(exc).__name__}
        if isinstance(exc, BrowserFetchError):
            metadata.update({"reason": exc.reason, "attempts": exc.attempts, "url": exc.url})
        return metadata

    def _trace(self, agent: str, action: str, status: str, detail: str, metadata: dict[str, str | int | float | bool] | None = None) -> AgentTrace:
        return AgentTrace(agent=agent, action=action, status=status, detail=detail, timestamp=datetime.utcnow(), metadata=metadata or {})
