from __future__ import annotations

import asyncio
import sys
from urllib.parse import urljoin

import requests
import trafilatura
from bs4 import BeautifulSoup

from app.config import get_settings
from app.models.schemas import BrowserAction, BrowserBrowseResponse


class BrowserAgent:
    def fetch(self, url: str, use_playwright: bool = False, actions: list[BrowserAction] | None = None) -> dict[str, object]:
        if use_playwright:
            result = self.browse(url, actions=actions or [])
            if not result.error:
                return result.model_dump()
        return self._fetch_static(url)

    def browse(self, url: str, actions: list[BrowserAction] | None = None) -> BrowserBrowseResponse:
        try:
            return self._browse_with_playwright(url, actions or [])
        except Exception as exc:
            fallback = self._fetch_static(url)
            return BrowserBrowseResponse(
                url=url,
                final_url=str(fallback.get("url") or url),
                title=str(fallback.get("title") or url),
                text=str(fallback.get("text") or ""),
                links=fallback.get("links", []),
                dom=fallback.get("dom", {}),
                used_playwright=False,
                actions=[],
                error=f"Playwright unavailable or failed, used static fallback: {exc}",
            )

    def _fetch_static(self, url: str) -> dict[str, object]:
        settings = get_settings()
        response = requests.get(url, timeout=settings.request_timeout_seconds, headers={"User-Agent": "AdmissionResearchAgent/0.1"})
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else url
        text = trafilatura.extract(html, url=url) or soup.get_text("\n", strip=True)
        links = self._extract_links(soup, url)
        return {"url": url, "final_url": response.url, "title": title, "text": text[:20000], "links": links, "dom": self._summarize_dom(soup), "used_playwright": False}

    def _browse_with_playwright(self, url: str, actions: list[BrowserAction]) -> BrowserBrowseResponse:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        self._ensure_playwright_event_loop_policy()
        settings = get_settings()
        action_results: list[dict[str, object]] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(user_agent="AdmissionResearchAgent/0.1")
            page.goto(url, wait_until="domcontentloaded", timeout=settings.request_timeout_seconds * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except PlaywrightTimeoutError:
                action_results.append({"type": "wait", "status": "timeout", "detail": "networkidle timeout"})
            for action in actions:
                action_results.append(self._run_action(page, action))
            html = page.content()
            final_url = page.url
            title = page.title() or final_url
            browser.close()
        soup = BeautifulSoup(html, "html.parser")
        text = trafilatura.extract(html, url=final_url) or soup.get_text("\n", strip=True)
        return BrowserBrowseResponse(
            url=url,
            final_url=final_url,
            title=title,
            text=text[:20000],
            links=self._extract_links(soup, final_url),
            dom=self._summarize_dom(soup),
            used_playwright=True,
            actions=action_results,
        )

    def _ensure_playwright_event_loop_policy(self) -> None:
        if sys.platform == "win32" and hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
            policy = asyncio.get_event_loop_policy()
            if not isinstance(policy, asyncio.WindowsProactorEventLoopPolicy):
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    def _run_action(self, page, action: BrowserAction) -> dict[str, object]:
        try:
            if action.type == "click" and action.selector:
                page.click(action.selector, timeout=5000)
                page.wait_for_load_state("domcontentloaded", timeout=5000)
                return {"type": action.type, "selector": action.selector, "status": "completed"}
            if action.type == "wait":
                value = int(action.value or 1000)
                page.wait_for_timeout(value)
                return {"type": action.type, "value": value, "status": "completed"}
            if action.type == "scroll":
                value = int(action.value or 1200)
                page.mouse.wheel(0, value)
                page.wait_for_timeout(500)
                return {"type": action.type, "value": value, "status": "completed"}
            return {"type": action.type, "status": "skipped", "detail": "missing selector or unsupported action"}
        except Exception as exc:
            return {"type": action.type, "selector": action.selector, "status": "failed", "error": str(exc)}

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
        links = []
        for anchor in soup.find_all("a", href=True)[:80]:
            label = anchor.get_text(" ", strip=True)
            href = urljoin(base_url, anchor["href"])
            if label and href.startswith("http"):
                links.append({"text": label[:120], "url": href})
        return links

    def _summarize_dom(self, soup: BeautifulSoup) -> dict[str, object]:
        headings = []
        for tag in soup.find_all(["h1", "h2", "h3"]):
            text = tag.get_text(" ", strip=True)
            if text:
                headings.append({"tag": tag.name, "text": text[:160]})
        forms = []
        for form in soup.find_all("form")[:10]:
            forms.append(
                {
                    "action": form.get("action") or "",
                    "method": form.get("method") or "get",
                    "inputs": [item.get("name") or item.get("id") or item.get("type") or "input" for item in form.find_all(["input", "select", "textarea"])[:20]],
                }
            )
        return {
            "headings": headings[:30],
            "forms": forms,
            "tables": len(soup.find_all("table")),
            "links_count": len(soup.find_all("a", href=True)),
            "text_length": len(soup.get_text(" ", strip=True)),
        }
