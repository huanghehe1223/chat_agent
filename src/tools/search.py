"""Tavily-backed search tool."""

from __future__ import annotations

from typing import Any

import requests


class SearchError(RuntimeError):
    """Raised when search cannot be executed."""


def tavily_search(
    query: str,
    max_results: int = 3,
    api_key: str = "",
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Search the web through Tavily and return compact results."""

    if not isinstance(query, str) or not query.strip():
        raise SearchError("query must be a non-empty string.")
    if not api_key:
        raise SearchError("TAVILY_API_KEY is required for search.")

    result_count = _normalize_max_results(max_results)
    payload = {
        "api_key": api_key,
        "query": query.strip(),
        "max_results": result_count,
        "search_depth": "basic",
        "include_answer": True,
    }

    try:
        response = requests.post("https://api.tavily.com/search", json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise SearchError(f"Tavily search request failed: {exc}") from exc
    except ValueError as exc:
        raise SearchError("Tavily search response was not valid JSON.") from exc

    results = []
    for item in data.get("results", [])[:result_count]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
            }
        )

    return {
        "query": query.strip(),
        "answer": data.get("answer", ""),
        "results": results,
    }


def _normalize_max_results(max_results: int) -> int:
    try:
        value = int(max_results)
    except (TypeError, ValueError) as exc:
        raise SearchError("max_results must be an integer.") from exc

    if value < 1:
        raise SearchError("max_results must be at least 1.")
    return min(value, 5)
