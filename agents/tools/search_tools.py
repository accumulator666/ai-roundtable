import httpx
from crewai.tools import tool


@tool("web_search")
def web_search(query: str, num_results: int = 10) -> str:
    """Search the web using SearXNG. Returns titles, URLs, and snippets."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.get("http://gluetun:8080/search", params={
            "q": query, "format": "json", "categories": "general", "pageno": 1
        })
        if resp.status_code != 200:
            return f"Search failed: HTTP {resp.status_code}"
        data = resp.json()
        results = data.get("results", [])[:num_results]
        if not results:
            return "No results found."
        lines = []
        for r in results:
            lines.append(f"  [{r.get('title', 'N/A')}]({r.get('url', '')})\n    {r.get('content', '')[:200]}")
        return f"Search results for '{query}':\n" + "\n\n".join(lines)


@tool("ai_research")
def ai_research(topic: str) -> str:
    """Ask the Grok AI researcher to analyze a topic in depth."""
    with httpx.Client(timeout=120.0) as client:
        resp = client.post("http://ai-mesh-router:8000/v1/chat/completions", json={
            "model": "grok-3",
            "messages": [
                {"role": "system", "content": "You are a business researcher. Provide detailed, actionable market analysis with data points, competitor info, and opportunity assessment."},
                {"role": "user", "content": f"Research this business opportunity in depth: {topic}"}
            ],
            "max_tokens": 4096
        })
        if resp.status_code != 200:
            return f"Research failed: {resp.text}"
        return resp.json()["choices"][0]["message"]["content"]
