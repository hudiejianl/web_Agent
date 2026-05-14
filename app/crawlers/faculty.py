from __future__ import annotations

from app.agents.browser_agent import BrowserAgent
from app.agents.research_agent import ResearchAgent
from app.models.schemas import TutorProfile


class FacultyCrawler:
    def __init__(self, browser: BrowserAgent | None = None, researcher: ResearchAgent | None = None):
        self.browser = browser or BrowserAgent()
        self.researcher = researcher or ResearchAgent()

    def crawl(self, url: str) -> TutorProfile:
        page = self.browser.fetch(url)
        return self.researcher.structure_faculty_page(page)
