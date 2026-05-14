from __future__ import annotations

from urllib.parse import urljoin

import requests
import trafilatura
from bs4 import BeautifulSoup

from app.config import get_settings


class BrowserAgent:
    def fetch(self, url: str) -> dict[str, object]:
        settings = get_settings()
        response = requests.get(url, timeout=settings.request_timeout_seconds, headers={"User-Agent": "AdmissionResearchAgent/0.1"})
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else url
        text = trafilatura.extract(html, url=url) or soup.get_text("\n", strip=True)
        links = []
        for anchor in soup.find_all("a", href=True)[:50]:
            label = anchor.get_text(" ", strip=True)
            href = urljoin(url, anchor["href"])
            if label and href.startswith("http"):
                links.append({"text": label, "url": href})
        return {"url": url, "title": title, "text": text[:20000], "links": links}
