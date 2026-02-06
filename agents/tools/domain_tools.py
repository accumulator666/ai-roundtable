import os
import httpx
from crewai.tools import tool

CF_KEY = os.environ.get("CLOUDFLARE_API_KEY", "")
CF_ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CF_URL = "https://api.cloudflare.com/client/v4"


def _cf_headers():
    return {"Authorization": f"Bearer {CF_KEY}", "Content-Type": "application/json"}


@tool("check_domain_available")
def check_domain_available(domain: str) -> str:
    """Check if a domain is available for registration via Cloudflare."""
    with httpx.Client() as client:
        resp = client.get(
            f"{CF_URL}/accounts/{CF_ACCOUNT}/registrar/domains/{domain}",
            headers=_cf_headers()
        )
        data = resp.json()
        if not data.get("success"):
            return f"Domain {domain} appears available (not in your account)."
        info = data.get("result", {})
        return f"Domain {domain}: status={info.get('status', 'unknown')}, expires={info.get('expires_at', 'N/A')}"


@tool("register_domain")
def register_domain(domain: str) -> str:
    """Register a domain via Cloudflare Registrar."""
    with httpx.Client() as client:
        resp = client.post(
            f"{CF_URL}/accounts/{CF_ACCOUNT}/registrar/domains/{domain}/register",
            headers=_cf_headers(),
            json={"auto_renew": True}
        )
        data = resp.json()
        if data.get("success"):
            return f"Domain {domain} registered successfully!"
        errors = data.get("errors", [])
        return f"Registration failed: {errors}"


@tool("setup_dns")
def setup_dns(domain: str, record_type: str, name: str, content: str) -> str:
    """Set up a DNS record for a domain. record_type: A, CNAME, etc."""
    with httpx.Client() as client:
        zones = client.get(f"{CF_URL}/zones", headers=_cf_headers(), params={"name": domain}).json()
        zone_results = zones.get("result", [])
        if not zone_results:
            return f"Zone not found for {domain}. Register the domain first."
        zone_id = zone_results[0]["id"]

        resp = client.post(f"{CF_URL}/zones/{zone_id}/dns_records", headers=_cf_headers(), json={
            "type": record_type, "name": name, "content": content, "proxied": True
        })
        data = resp.json()
        if data.get("success"):
            return f"DNS record created: {record_type} {name} -> {content}"
        return f"DNS setup failed: {data.get('errors', [])}"
