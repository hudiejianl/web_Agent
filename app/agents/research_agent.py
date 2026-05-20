from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.llm.provider import get_llm_client
from app.models.schemas import Evidence, Paper, TutorProfile


AREA_KEYWORDS = ["人工智能", "机器学习", "深度学习", "大模型", "自然语言处理", "信息检索", "软件工程", "程序分析", "医学影像", "数据挖掘", "计算机视觉", "数据库", "数据管理", "数据分析", "多媒体", "云计算", "大数据", "电子政务"]


class ResearchAgent:
    def structure_faculty_page(self, page: dict[str, object]) -> TutorProfile:
        llm_profile = self._structure_with_llm(page)
        if llm_profile:
            return llm_profile
        text = str(page.get("text") or "")
        title = str(page.get("title") or "导师主页")
        url = str(page.get("url") or "")
        name = self._guess_name(title, text)
        institution = self._guess_institution(text)
        research_areas = [keyword for keyword in AREA_KEYWORDS if keyword in text]
        papers = [Paper(title=item) for item in self._guess_papers(text)]
        summary = text[:300].replace("\n", " ")
        return TutorProfile(
            name=name,
            title=self._guess_title(text),
            institution=institution,
            department=self._guess_department(text),
            location=self._guess_location(text),
            homepage=url,
            email=self._guess_email(text),
            research_areas=research_areas,
            admission_directions=research_areas[:4],
            requirements=self._guess_requirements(text),
            papers=papers,
            summary=summary,
            evidence=[Evidence(title=title, url=url, snippet=summary[:180])],
        )

    def _structure_with_llm(self, page: dict[str, object]) -> TutorProfile | None:
        client = get_llm_client()
        if not client.available:
            return None
        text = str(page.get("text") or "")[:9000]
        title = str(page.get("title") or "导师主页")
        url = str(page.get("url") or "")
        system = (
            "你是导师主页信息抽取 Agent。请只输出 JSON，不要输出 Markdown。"
            "JSON 字段必须兼容：name,title,institution,department,location,homepage,email,research_areas,admission_directions,requirements,papers,summary,evidence。"
            "papers 是对象数组，字段包括 title,year,venue,url,doi,abstract；evidence 是对象数组，字段包括 title,url,snippet。无法确定的字段用 null 或空数组。"
        )
        user = f"页面标题：{title}\n页面 URL：{url}\n网页正文：{text}"
        result = client.complete(system=system, user=user, temperature=0.0, max_tokens=1600)
        if not result.content:
            return None
        try:
            payload = self._json_from_text(result.content)
            payload["homepage"] = payload.get("homepage") or url
            if not payload.get("evidence"):
                payload["evidence"] = [{"title": title, "url": url, "snippet": text[:180]}]
            return TutorProfile.model_validate(payload)
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError):
            return None

    def _json_from_text(self, text: str) -> dict[str, object]:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON object found")
        return json.loads(stripped[start : end + 1])

    def _guess_name(self, title: str, text: str) -> str:
        invalid_names = {"个人信息", "中文主页", "教师主页", "科学研究", "教育经历", "工作经历", "研究方向", "团队成员", "联系方式", "其他联系", "首页", "大学主页", "平台管理", "管理系统", "教授", "副教授", "讲师", "研究员", "导师", "博导", "硕导"}
        for pattern in [r"姓名[:：]\s*([一-龥]{2,4})", r"^\s*([一-龥]{2,4})\s*$", r"([一-龥]{2,4})\s*(教授|副教授|研究员|讲师|硕士生导师|博士生导师)"]:
            match = re.search(pattern, text, flags=re.MULTILINE)
            if match and match.group(1) not in invalid_names:
                return match.group(1)
        title_name_match = re.search(r"\s([一-龥]{2,4})--", title)
        if title_name_match and title_name_match.group(1) not in invalid_names:
            return title_name_match.group(1)
        title_matches = [match for match in re.findall(r"[一-龥]{2,4}", title) if match not in invalid_names and not match.endswith("大学")]
        if title_matches:
            return title_matches[-1]
        return title.split("-")[0].split("_")[0].strip()[:20] or "未知导师"

    def _guess_title(self, text: str) -> str | None:
        for title in ["教授", "副教授", "研究员", "讲师", "助理教授"]:
            if title in text:
                return title
        return None

    def _guess_institution(self, text: str) -> str:
        if "华中科技大学" in text:
            return "华中科技大学"
        match = re.search(r"([一-龥]{2,20}(大学|学院|研究所))", text)
        return match.group(1) if match else "未知机构"

    def _guess_department(self, text: str) -> str | None:
        match = re.search(r"([一-龥]{2,20}(学院|系|实验室|中心))", text)
        return match.group(1) if match else None

    def _guess_location(self, text: str) -> str | None:
        for location in ["北京", "上海", "杭州", "南京", "广州", "深圳", "武汉", "西安"]:
            if location in text:
                return location
        return None

    def _guess_email(self, text: str) -> str | None:
        match = re.search(r"[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}", text)
        return match.group(0) if match else None

    def _guess_papers(self, text: str) -> list[str]:
        candidates = []
        for line in text.splitlines():
            stripped = line.strip(" -•\t")
            if 20 <= len(stripped) <= 180 and any(token in stripped.lower() for token in ["learning", "agent", "retrieval", "analysis", "generation"]):
                candidates.append(stripped)
        return candidates[:8]

    def _guess_requirements(self, text: str) -> list[str]:
        requirements = []
        for keyword in ["Python", "PyTorch", "数学", "论文", "英语", "编程", "科研"]:
            if keyword.lower() in text.lower():
                requirements.append(f"具备{keyword}相关能力")
        return requirements[:5]
