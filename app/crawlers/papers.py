from __future__ import annotations

import re

from app.models.schemas import Paper


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(20\d{2}|19\d{2})\b")


def extract_papers(text: str) -> list[Paper]:
    papers: list[Paper] = []
    for line in text.splitlines():
        stripped = line.strip(" -•\t")
        if len(stripped) < 20:
            continue
        doi = DOI_PATTERN.search(stripped)
        year = YEAR_PATTERN.search(stripped)
        if doi or any(word in stripped.lower() for word in ["learning", "agent", "retrieval", "analysis", "generation", "network"]):
            papers.append(Paper(title=stripped[:180], doi=doi.group(0) if doi else None, year=int(year.group(1)) if year else None))
    return papers[:20]
