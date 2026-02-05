import os
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
import time

app = FastAPI(title="ChatGPT Proxy", version="1.0.0")

API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = "https://api.openai.com"
AVAILABLE_MODELS = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o3-mini"]


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")

    body = await request.json()
    stream = body.get("stream", False)

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    if stream:
        async def forward_stream():
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", f"{BASE_URL}/v1/chat/completions",
                    headers=headers, json=body,
                ) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk

        return StreamingResponse(forward_stream(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{BASE_URL}/v1/chat/completions", headers=headers, json=body
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "created": int(time.time()), "owned_by": "openai"}
            for m in AVAILABLE_MODELS
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "chatgpt-proxy", "models": AVAILABLE_MODELS}
