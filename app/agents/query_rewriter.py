from __future__ import annotations

import json
import re

from app.llm.provider import get_llm_client


DEFAULT_ALLOWED_DOMAINS = ["edu.cn", "hust.edu.cn", "whut.edu.cn", "wdu.edu.cn"]
LOCATION_SCHOOL_DOMAINS = {
    "武汉": ["hust.edu.cn", "whut.edu.cn", "whu.edu.cn", "ccnu.edu.cn"],
    "上海": ["sjtu.edu.cn", "fudan.edu.cn", "tongji.edu.cn", "ecnu.edu.cn"],
    "北京": ["tsinghua.edu.cn", "pku.edu.cn", "buaa.edu.cn", "bit.edu.cn"],
    "南京": ["nju.edu.cn", "seu.edu.cn", "njupt.edu.cn"],
    "杭州": ["zju.edu.cn", "hznu.edu.cn"],
}
RESEARCH_TERMS = ["人工智能", "计算机", "多模态", "大模型", "RAG", "自然语言处理", "机器学习", "计算机视觉", "软件工程", "数据挖掘"]


class QueryRewriter:
    def rewrite(self, user_query: str, allowed_domains: list[str] | None = None, max_queries: int = 5) -> list[str]:
        domains = allowed_domains or DEFAULT_ALLOWED_DOMAINS
        queries = self._rewrite_with_llm(user_query, domains, max_queries)
        if not queries:
            queries = self._rewrite_with_rules(user_query, domains)
        return self._normalize_queries(queries, max_queries)

    def _rewrite_with_llm(self, user_query: str, domains: list[str], max_queries: int) -> list[str]:
        client = get_llm_client()
        if not client.available:
            return []
        system = (
            "你是升学信息检索 Query Rewriter。请把用户目标改写为适合搜索高校导师主页的搜索 Query。"
            "只输出 JSON 数组，不要 Markdown。Query 应尽量包含 site: 域名限制、地区、学院/导师/教师主页、研究方向。"
        )
        user = f"用户目标：{user_query}\n允许优先域名：{', '.join(domains)}\n最多输出 {max_queries} 条。"
        result = client.complete(system=system, user=user, temperature=0.1, max_tokens=500)
        if not result.content:
            return []
        try:
            payload = json.loads(self._json_array_from_text(result.content))
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
        return [str(item) for item in payload if isinstance(item, str)]

    def _rewrite_with_rules(self, user_query: str, domains: list[str]) -> list[str]:
        locations = [location for location in LOCATION_SCHOOL_DOMAINS if location in user_query]
        terms = [term for term in RESEARCH_TERMS if term.lower() in user_query.lower()]
        if not terms:
            terms = ["计算机", "人工智能"] if any(word in user_query for word in ["导师", "老师", "教授"]) else [user_query]
        queries: list[str] = []
        location_text = " ".join(locations)
        term_text = " ".join(terms[:3])
        queries.append(f"site:{domains[0]} {location_text} {term_text} 计算机学院 导师".strip())
        queries.append(f"site:{domains[0]} {location_text} {term_text} 教师主页 研究方向".strip())
        for location in locations:
            for domain in LOCATION_SCHOOL_DOMAINS.get(location, [])[:3]:
                queries.append(f"site:{domain} {term_text} 导师 个人主页")
        for domain in domains[1:4]:
            queries.append(f"site:{domain} {location_text} {term_text} 导师")
        return queries

    def _normalize_queries(self, queries: list[str], max_queries: int) -> list[str]:
        normalized = []
        for query in queries:
            compact = re.sub(r"\s+", " ", query).strip()
            if compact and compact not in normalized:
                normalized.append(compact)
        return normalized[: max(1, max_queries)]

    def _json_array_from_text(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
        start = stripped.find("[")
        end = stripped.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("No JSON array found")
        return stripped[start : end + 1]
