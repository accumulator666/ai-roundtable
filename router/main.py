import asyncio
import json
import time
import uuid
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from routing import resolve_proxy_url, auto_select_model, get_all_models, check_health, MODEL_TO_PROXY
from delegation import extract_delegations, strip_delegations, publish_event

app = FastAPI(title="AI Router", version="1.0.0")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "auto"
    messages: list[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False


class DelegateRequest(BaseModel):
    target_model: str
    messages: list[ChatMessage]
    context: Optional[str] = None


class MultiRequest(BaseModel):
    models: list[str]
    messages: list[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    model = request.model
    if model == "auto":
        model = auto_select_model([m.model_dump() for m in request.messages])

    proxy_url = resolve_proxy_url(model)
    body = request.model_dump()
    body["model"] = model

    if request.stream:
        async def stream_forward():
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", f"{proxy_url}/v1/chat/completions", json=body
                ) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk

        return StreamingResponse(stream_forward(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{proxy_url}/v1/chat/completions", json=body)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        result = resp.json()

        # Check for delegation in response
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        delegations = extract_delegations(content)
        if delegations:
            target_model, delegate_prompt = delegations[0]
            delegate_url = resolve_proxy_url(target_model)
            delegate_body = {
                "model": target_model,
                "messages": [{"role": "user", "content": delegate_prompt.strip()}],
                "temperature": request.temperature,
            }
            delegate_resp = await client.post(
                f"{delegate_url}/v1/chat/completions", json=delegate_body
            )
            if delegate_resp.status_code == 200:
                delegate_result = delegate_resp.json()
                delegate_content = delegate_result["choices"][0]["message"]["content"]
                clean = strip_delegations(content)
                combined = f"{clean}\n\n---\n**[{target_model} response]:**\n{delegate_content}"
                result["choices"][0]["message"]["content"] = combined

                await publish_event("ai.delegation", {
                    "source": model,
                    "target": target_model,
                    "timestamp": time.time(),
                })

        await publish_event(f"ai.{model.split('-')[0]}", {
            "model": model,
            "tokens": result.get("usage", {}).get("total_tokens", 0),
            "timestamp": time.time(),
        })

        return result


@app.post("/v1/chat/delegate")
async def delegate(request: DelegateRequest):
    proxy_url = resolve_proxy_url(request.target_model)
    body = {
        "model": request.target_model,
        "messages": [m.model_dump() for m in request.messages],
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{proxy_url}/v1/chat/completions", json=body)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()


@app.post("/v1/chat/multi")
async def multi_completion(request: MultiRequest):
    async def call_model(model: str):
        proxy_url = resolve_proxy_url(model)
        body = {
            "model": model,
            "messages": [m.model_dump() for m in request.messages],
            "temperature": request.temperature,
        }
        if request.max_tokens:
            body["max_tokens"] = request.max_tokens
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                resp = await client.post(f"{proxy_url}/v1/chat/completions", json=body)
                return {"model": model, "status": "ok", "response": resp.json()}
            except Exception as e:
                return {"model": model, "status": "error", "error": str(e)}

    results = await asyncio.gather(*[call_model(m) for m in request.models])
    return {"results": list(results)}


@app.get("/v1/models")
async def list_models():
    models = await get_all_models()
    return {"object": "list", "data": models}


@app.get("/health")
async def health():
    statuses = await check_health()
    all_ok = all(s.get("status") == "ok" for s in statuses.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "service": "ai-router",
        "backends": statuses,
    }
