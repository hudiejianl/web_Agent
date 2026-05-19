from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.models.schemas import TutorProfile


@dataclass
class ProfileQualityResult:
    score: float = 0.0
    ingest_eligible: bool = False
    reasons: list[str] = field(default_factory=list)


class ProfileQualityScorer:
    def precheck_reasons(self, url: str, link_type: str = "profile") -> list[str]:
        normalized_url = url.lower()
        host = urlparse(normalized_url).netloc.lower()
        reasons: list[str] = []
        if any(domain in host for domain in ["bing.com", "baidu.com", "sogou.com", "so.com"]) or "/search?" in normalized_url:
            reasons.append("搜索结果页不能作为导师主页")
        if host.endswith("gov.cn") or "baike.baidu.com" in host:
            reasons.append("非导师主页来源")
        if link_type in {"school", "college", "faculty_list", "pagination", "paper"}:
            reasons.append(f"{link_type} 链接只用于导航发现，不直接入库")
        if any(token in normalized_url for token in ["login", "signin", "captcha"]):
            reasons.append("登录或验证码页面不采集")
        return reasons

    def score(self, profile: TutorProfile, url: str, title: str = "", text: str = "", link_type: str = "profile", page_quality: float = 0.0) -> ProfileQualityResult:
        normalized_url = (profile.homepage or url or "").lower()
        host = urlparse(normalized_url).netloc.lower()
        name = (profile.name or "").strip()
        page_text = f"{title or ''} {text or ''}"
        lower_text = page_text.lower()
        invalid_names = {"未知导师", "导师", "教师", "教授", "副教授", "讲师", "研究员", "特聘", "女副", "武汉市", "Professor", "Unknown"}
        hard_reasons: list[str] = []
        positive_reasons: list[str] = []
        score = 0.0

        hard_reasons.extend(self.precheck_reasons(normalized_url, link_type=link_type))
        if not name or name in invalid_names or len(name) > 12:
            hard_reasons.append("导师姓名不可信")
        elif any(token in name.lower() for token in ["site:", "http", "www", "search", "bing", "baidu"]) or any(token in name for token in ["æ", "å", "�"]):
            hard_reasons.append("导师姓名疑似噪声")
        else:
            score += 0.25
            positive_reasons.append("姓名可信")

        has_profile_context = link_type == "profile" or any(token in normalized_url for token in ["teacher", "tutor", "profile", "person", "teacherinfo"]) or any(token in page_text for token in ["个人主页", "教师简介", "导师简介", "研究方向"])
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

        score += min(page_quality * 0.17, 0.17)
        normalized_score = round(min(score, 1.0), 4)
        eligible = not hard_reasons and normalized_score >= 0.55
        reasons = hard_reasons or positive_reasons
        if not eligible and not hard_reasons:
            reasons = [*positive_reasons, "质量分低于入库阈值"]
        return ProfileQualityResult(score=normalized_score, ingest_eligible=eligible, reasons=reasons)
