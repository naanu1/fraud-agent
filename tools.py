"""
Three tools only. Each returns a plain string of text content.
  web_search(query)        -- Tavily broad search, returns combined text
  targeted_search(query)   -- Serper Google search (site: operators), returns combined text
  sanctions_check(name)    -- OpenSanctions API, returns match summary string
"""
import requests
import logging
from config import TAVILY_API_KEY, SERPER_API_KEY, OPENSANCTIONS_API_KEY

log = logging.getLogger("tools")


def web_search(query: str, max_results: int = 4) -> str:
    """Tavily: broad web search for news, background, general info."""
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": TAVILY_API_KEY, "query": query,
                  "max_results": max_results, "include_raw_content": False},
            timeout=18,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        parts = []
        for r in results:
            url  = r.get("url", "")
            text = r.get("content", "")
            if url and text:
                parts.append(f"[SOURCE: {url}]\n{text[:1500]}")
        out = "\n\n".join(parts)
        log.info(f"web_search: {len(results)} results for '{query[:60]}'")
        return out  # empty string = no results (caller checks len)
    except Exception as e:
        log.warning(f"web_search failed ({query[:50]}): {e}")
        return ""  # empty string = failed (caller checks len)


_FETCH_DOMAINS = ("sec.gov", "finra.org", "justice.gov", "courtlistener.com")


def targeted_search(query: str, max_results: int = 4) -> str:
    """Serper: targeted Google search. Falls back to Tavily if key missing or no results.
    For authoritative domains (SEC/FINRA), also fetches the top result's full content."""
    if not SERPER_API_KEY:
        return web_search(query, max_results)
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": max_results},
            timeout=12,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("organic", [])
        parts = []
        top_fetch_url = None
        for r in results:
            url     = r.get("link", "")
            snippet = r.get("snippet", "")
            title   = r.get("title", "")
            if url and snippet:
                parts.append(f"[SOURCE: {url}]\n{title}\n{snippet}")
            # Track first authoritative URL for deep fetch
            if not top_fetch_url and url and any(d in url for d in _FETCH_DOMAINS):
                top_fetch_url = url
        out = "\n\n".join(parts)
        log.info(f"targeted_search: {len(results)} results for '{query[:60]}'")
        if not out:
            return web_search(query, max_results)
        # Fetch full content from top authoritative URL (SEC/FINRA PDFs etc.)
        if top_fetch_url:
            full = _fetch(top_fetch_url)
            if full and len(full) > 200:
                out += f"\n\n=== FULL DOCUMENT: {top_fetch_url} ===\n{full}"
                log.info(f"targeted_search: fetched {len(full)} chars from {top_fetch_url[:60]}")
        return out
    except Exception as e:
        log.warning(f"targeted_search failed ({query[:50]}): {e} — falling back to Tavily")
        return web_search(query, max_results)


def sanctions_check(name: str) -> str:
    """OpenSanctions: check OFAC/UN/EU/Interpol watchlists by name."""
    try:
        resp = requests.post(
            "https://api.opensanctions.org/match/sanctions",
            headers={
                "Authorization": f"ApiKey {OPENSANCTIONS_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"queries": {"q1": {"schema": "Person", "properties": {"name": [name]}}}},
            timeout=15,
        )
        resp.raise_for_status()
        data    = resp.json()
        results = data.get("responses", {}).get("q1", {}).get("results", [])
        if not results:
            return ""
        lines = [f"SANCTIONS HIT for '{name}':"]
        for r in results[:3]:
            caption  = r.get("caption", "")
            datasets = ", ".join(r.get("datasets", []))
            score    = r.get("score", 0)
            lines.append(f"  - {caption} | Lists: {datasets} | Score: {score:.2f}")
        return "\n".join(lines)
    except Exception as e:
        log.warning(f"sanctions_check failed ({name}): {e}")
        return ""


def _fetch(url: str) -> str:
    """Fetch full text of a URL via Tavily extract. Returns up to 12000 chars."""
    try:
        resp = requests.post(
            "https://api.tavily.com/extract",
            json={"api_key": TAVILY_API_KEY, "urls": [url]},
            timeout=25,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if results:
            return results[0].get("raw_content", "")[:12000]
    except Exception:
        pass
    return ""
