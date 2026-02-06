import os
import httpx
from crewai.tools import tool

RESEND_KEY = os.environ.get("RESEND_API_KEY", "")


@tool("send_email")
def send_email(to: str, subject: str, html_body: str, from_email: str = "onboarding@resend.dev") -> str:
    """Send an email via Resend. Use from_email with your verified domain, or onboarding@resend.dev for testing."""
    with httpx.Client() as client:
        resp = client.post("https://api.resend.com/emails", headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
        }, json={
            "from": from_email,
            "to": [to],
            "subject": subject,
            "html": html_body,
        })
        data = resp.json()
        if "id" in data:
            return f"Email sent successfully. ID: {data['id']}"
        return f"Email failed: {data}"


@tool("send_notification")
def send_notification(subject: str, message: str) -> str:
    """Send a notification email to the system owner."""
    owner_email = os.environ.get("OWNER_EMAIL", "")
    if not owner_email:
        return "OWNER_EMAIL not configured. Cannot send notification."
    return send_email.run(to=owner_email, subject=f"[AI Mesh] {subject}", html_body=f"<p>{message}</p>")
