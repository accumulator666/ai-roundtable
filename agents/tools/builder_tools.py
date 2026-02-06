import os
import httpx
from crewai.tools import tool


@tool("build_code")
def build_code(prompt: str) -> str:
    """Send a coding task to Claude Code. It can create files, write code, and build projects."""
    with httpx.Client(timeout=300.0) as client:
        resp = client.post("http://claude-code:8000/v1/code/execute", json={
            "prompt": prompt,
            "working_dir": "/workspace"
        })
        if resp.status_code != 200:
            return f"Build failed: {resp.text}"
        data = resp.json()
        return f"Build completed:\n{data.get('output', 'No output')}"


@tool("deploy_to_cloudflare")
def deploy_to_cloudflare(project_name: str, directory: str = "/workspace/build") -> str:
    """Deploy a static site to Cloudflare Pages."""
    cf_key = os.environ.get("CLOUDFLARE_API_KEY", "")
    cf_account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/pages/projects",
            headers={"Authorization": f"Bearer {cf_key}", "Content-Type": "application/json"},
            json={"name": project_name, "production_branch": "main"}
        )
        data = resp.json()
        subdomain = f"{project_name}.pages.dev"
        return f"Cloudflare Pages project created: {subdomain}\nDeploy files to it via Wrangler CLI or API upload."


@tool("ai_generate_content")
def ai_generate_content(prompt: str, style: str = "professional") -> str:
    """Generate marketing content using GPT-4o."""
    with httpx.Client(timeout=120.0) as client:
        resp = client.post("http://ai-mesh-router:8000/v1/chat/completions", json={
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": f"You are an expert copywriter. Write in a {style} style. Be concise, persuasive, and conversion-focused."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 4096
        })
        if resp.status_code != 200:
            return f"Content generation failed: {resp.text}"
        return resp.json()["choices"][0]["message"]["content"]
