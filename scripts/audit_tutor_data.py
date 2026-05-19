from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.schemas import TutorProfile
from app.services.ingestion import ensure_seed_data
from app.storage.database import get_connection, init_database


NOISE_TOKENS = ["无法访问", "404", "403", "登录", "验证码", "captcha", "hotel", "旅游", "新闻", "百度", "bing", "首页", "无标题", "未知", "N/A"]
INVALID_NAMES = {"未知导师", "示例导师", "导师", "教师", "教授", "副教授", "讲师", "研究员", "特聘", "女副", "武汉市", "Professor", "Unknown"}
INVALID_HOST_TOKENS = ["bing.com", "baidu.com", "sogou.com", "so.com", "gov.cn"]


@dataclass
class TutorQualityIssue:
    name: str
    homepage: str
    reasons: list[str]


@dataclass
class TutorAuditReport:
    total: int
    valid: int
    invalid: int
    duplicate_names: list[str]
    missing_research_areas: list[str]
    missing_homepage: list[str]
    locations: dict[str, int]
    institutions: dict[str, int]
    issues: list[TutorQualityIssue]


def load_profiles() -> list[TutorProfile]:
    init_database()
    ensure_seed_data()
    with get_connection() as connection:
        rows = connection.execute("SELECT payload FROM tutors ORDER BY updated_at DESC").fetchall()
    return [TutorProfile.model_validate_json(row["payload"]) for row in rows]


def audit_profiles(profiles: list[TutorProfile]) -> TutorAuditReport:
    duplicate_names = sorted(name for name, count in Counter(profile.name for profile in profiles).items() if count > 1)
    issues = []
    for profile in profiles:
        reasons = quality_reasons(profile)
        if reasons:
            issues.append(TutorQualityIssue(name=profile.name, homepage=profile.homepage or "", reasons=reasons))
    return TutorAuditReport(
        total=len(profiles),
        valid=len(profiles) - len(issues),
        invalid=len(issues),
        duplicate_names=duplicate_names,
        missing_research_areas=[profile.name for profile in profiles if not profile.research_areas],
        missing_homepage=[profile.name for profile in profiles if not profile.homepage],
        locations=dict(Counter(profile.location or "未识别" for profile in profiles)),
        institutions=dict(Counter(profile.institution or "未识别" for profile in profiles)),
        issues=issues,
    )


def quality_reasons(profile: TutorProfile) -> list[str]:
    reasons = []
    homepage = (profile.homepage or "").lower()
    searchable = " ".join([
        profile.name,
        profile.institution,
        profile.department or "",
        profile.homepage or "",
        " ".join(profile.research_areas),
        profile.summary,
    ]).lower()
    if not profile.homepage:
        reasons.append("missing_homepage")
    if any(token in homepage for token in INVALID_HOST_TOKENS) or "/search?" in homepage:
        reasons.append("invalid_source_url")
    if profile.name in INVALID_NAMES or len(profile.name.strip()) <= 1 or len(profile.name.strip()) > 12:
        reasons.append("invalid_name")
    if any(token in profile.name.lower() for token in ["site:", "http", "www", "search", "bing", "baidu"]) or any(token in profile.name for token in ["æ", "å", "�"]):
        reasons.append("noisy_name")
    if not profile.research_areas:
        reasons.append("missing_research_areas")
    if profile.institution == "未知机构" and not profile.department:
        reasons.append("missing_institution")
    noise_hits = [token for token in NOISE_TOKENS if token.lower() in searchable]
    if noise_hits:
        reasons.append("noise_tokens:" + ",".join(noise_hits))
    return reasons


def report_to_dict(report: TutorAuditReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["quality_passed"] = report.invalid == 0
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit stored tutor profiles for noisy or invalid records.")
    parser.add_argument("--fail-on-invalid", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    report = audit_profiles(load_profiles())
    payload = report_to_dict(report)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if args.fail_on_invalid and report.invalid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
