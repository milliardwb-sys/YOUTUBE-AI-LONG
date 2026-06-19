# Search Provider Foundation Update - 2026-06-19

This update closes the first practical slice of the production backlog item "real source search/research provider".

## Implemented

- Search provider abstraction in `backend/app/services/search_provider.py`.
- Providers:
  - `disabled`: default offline-safe provider.
  - `brave`: Brave Search API compatible provider.
- Brave provider uses the official web search endpoint:
  - `https://api.search.brave.com/res/v1/web/search`
  - auth header: `X-Subscription-Token`
- New backend settings:
  - `SEARCH_PROVIDER=disabled|brave`
  - `BRAVE_SEARCH_API_KEY`
  - `BRAVE_SEARCH_ENDPOINT`
  - `SEARCH_RESULT_COUNT`
- `/providers` now reports search provider configuration status.
- `SourceService` now collects sources in this order:
  - user-provided URLs;
  - search provider results;
  - curated fallback sources.
- Search result URLs pass the existing SSRF/source URL validation before screenshot/fallback-card processing.
- Search provider failure never breaks local generation; the pipeline records a warning and falls back to curated sources.
- New `SourceKind.search_result` marks provider-derived sources.
- Backend tests cover:
  - SourceService using provider results;
  - Brave parser filtering unsafe/private URLs;
  - existing official source/slide flow remains intact.

## Configuration

Default offline mode:

```text
SEARCH_PROVIDER=disabled
```

Brave Search mode:

```text
SEARCH_PROVIDER=brave
BRAVE_SEARCH_API_KEY=<your Brave Search API key>
SEARCH_RESULT_COUNT=3
```

## Verified

- Targeted source/search tests:
  - `3 passed, 50 deselected`

## Still Not Production-Complete

- Search results are used as candidate sources, not as a full research/fact-checking layer.
- There is no source confidence score, citation review UI, or human approval workflow yet.
- There is no LLM grounding/research synthesis step before script generation.
- There is no provider-side quota dashboard or billing reconciliation.
- There is no caching layer for search responses.
- There is no domain allow/deny policy beyond the existing SSRF/private-network guard.

## Sources

- Brave Search API overview: https://brave.com/search/api/
- Brave Web Search documentation/API reference: https://api-dashboard.search.brave.com/app/documentation/web-search/get-started
