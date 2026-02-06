import os
import httpx
from crewai.tools import tool

STRIPE_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_URL = "https://api.stripe.com/v1"


def _stripe_headers():
    return {"Authorization": f"Bearer {STRIPE_KEY}"}


@tool("create_stripe_product")
def create_stripe_product(name: str, description: str, price_cents: int, currency: str = "usd", recurring: str = None) -> str:
    """Create a Stripe product with a price. Set recurring to 'month' or 'year' for subscriptions."""
    with httpx.Client() as client:
        product = client.post(f"{STRIPE_URL}/products", headers=_stripe_headers(), data={
            "name": name, "description": description
        }).json()

        if "error" in product:
            return f"Error creating product: {product['error']['message']}"

        price_data = {
            "product": product["id"],
            "unit_amount": price_cents,
            "currency": currency,
        }
        if recurring:
            price_data["recurring[interval]"] = recurring

        price = client.post(f"{STRIPE_URL}/prices", headers=_stripe_headers(), data=price_data).json()

        if "error" in price:
            return f"Product created ({product['id']}) but price failed: {price['error']['message']}"

        link = client.post(f"{STRIPE_URL}/payment_links", headers=_stripe_headers(), data={
            "line_items[0][price]": price["id"],
            "line_items[0][quantity]": 1,
        }).json()

        payment_url = link.get("url", "N/A")
        return f"Product: {product['id']}\nPrice: {price['id']}\nPayment link: {payment_url}"


@tool("get_stripe_balance")
def get_stripe_balance() -> str:
    """Get current Stripe account balance."""
    with httpx.Client() as client:
        balance = client.get(f"{STRIPE_URL}/balance", headers=_stripe_headers()).json()
        if "error" in balance:
            return f"Error: {balance['error']['message']}"
        available = sum(b["amount"] for b in balance.get("available", []))
        pending = sum(b["amount"] for b in balance.get("pending", []))
        return f"Available: ${available/100:.2f}\nPending: ${pending/100:.2f}"


@tool("list_recent_payments")
def list_recent_payments(limit: int = 10) -> str:
    """List recent successful payments."""
    with httpx.Client() as client:
        charges = client.get(f"{STRIPE_URL}/charges", headers=_stripe_headers(), params={
            "limit": limit, "status": "succeeded"
        }).json()
        if "error" in charges:
            return f"Error: {charges['error']['message']}"
        lines = []
        for c in charges.get("data", []):
            lines.append(f"  ${c['amount']/100:.2f} - {c.get('description', 'N/A')} ({c['created']})")
        return f"Recent payments ({len(lines)}):\n" + "\n".join(lines) if lines else "No recent payments."
