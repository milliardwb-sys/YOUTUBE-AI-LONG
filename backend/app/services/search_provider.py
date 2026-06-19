from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import Settings
from app.utils.security import UnsafeUrlError, validate_source_url


class SearchProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    description: str


class SearchProvider:
    def search(self, query: str, *, count: int, language: str = "en") -> list[SearchResult]:
        raise NotImplementedError


class DisabledSearchProvider(SearchProvider):
    def search(self, query: str, *, count: int, language: str = "en") -> list[SearchResult]:
        return []


class BraveSearchProvider(SearchProvider):
    def __init__(self, settings: Settings):
        if not settings.brave_search_api_key:
            raise SearchProviderUnavailable("BRAVE_SEARCH_API_KEY is not configured")
        self.settings = settings

    def search(self, query: str, *, count: int, language: str = "en") -> list[SearchResult]:
        if count <= 0:
            return []
        params = {
            "q": query,
            "count": str(min(max(1, count), 10)),
            "search_lang": "ru" if language == "ru" else "en",
        }
        url = f"{self.settings.brave_search_endpoint}?{urlencode(params)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "AI-Video-Studio-MVP/0.4",
                "X-Subscription-Token": self.settings.brave_search_api_key or "",
            },
        )
        with urlopen(request, timeout=8) as response:  # noqa: S310 - endpoint is configured and validated below
            payload = json.loads(response.read().decode("utf-8"))
        return self._parse_results(payload)

    def _parse_results(self, payload: dict) -> list[SearchResult]:
        results: list[SearchResult] = []
        for item in payload.get("web", {}).get("results", []):
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            description = str(item.get("description") or item.get("snippet") or "").strip()
            if not title or not url:
                continue
            try:
                validate_source_url(url, self.settings)
            except UnsafeUrlError:
                continue
            results.append(SearchResult(title=title[:140], url=url, description=description[:500]))
        return results


def make_search_provider(settings: Settings) -> SearchProvider:
    if settings.search_provider == "brave":
        return BraveSearchProvider(settings)
    return DisabledSearchProvider()
