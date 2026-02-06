import os
import json
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import time
import uuid

app = FastAPI(title="Claude Proxy", version="1.0.0")

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BASE_URL = "https://api.anthropic.com"
MODEL_ALIASES = {
    "claude-opus-4-6": "claude-opus-4-6",
    "claude-sonnet-4-5": "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
}


class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatRequest(BaseModel):
    model: str = "claude-sonnet-4-5"
    messages: list[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 4096
    stream: Optional[bool] = False
    top_p: Optional[float] = None


def to_anthropic_messages(messages: list[ChatMessage]) -> tuple[str, list[dict]]:
    system = ""
    converted = []
    for msg in messages:
        if msg.role == "system":
            system += ("\n" + msg.content if system else msg.content)
        else:
            role = msg.role if msg.role in ("user", "assistant") else "user"
            # Merge consecutive same-role messages (Anthropic API requires alternating roles)
            if converted and converted[-1]["role"] == role:
                converted[-1]["content"] += "\n" + msg.content
            else:
                converted.append({"role": role, "content": msg.content})

    # Strip trailing assistant messages (prefills not supported by all models)
    while converted and converted[-1]["role"] == "assistant":
        converted.pop()

    # Ensure conversation starts with user message
    if converted and converted[0]["role"] != "user":
        converted.insert(0, {"role": "user", "content": "Continue."})

    # Ensure at least one message
    if not converted:
        converted = [{"role": "user", "content": "Hello."}]

    return system, converted


def to_openai_response(anthropic_resp: dict, model: str) -> dict:
    content = ""
    for block in anthropic_resp.get("content", []):
        if block["type"] == "text":
            content += block["text"]

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": anthropic_resp.get("stop_reason", "end_turn"),
            }
        ],
        "usage": {
            "prompt_tokens": anthropic_resp.get("usage", {}).get("input_tokens", 0),
            "completion_tokens": anthropic_resp.get("usage", {}).get("output_tokens", 0),
            "total_tokens": anthropic_resp.get("usage", {}).get("input_tokens", 0)
            + anthropic_resp.get("usage", {}).get("output_tokens", 0),
        },
    }


async def stream_anthropic(request: ChatRequest):
    system, messages = to_anthropic_messages(request.messages)
    model_id = MODEL_ALIASES.get(request.model, request.model)

    body = {
        "model": model_id,
        "messages": messages,
        "max_tokens": request.max_tokens or 4096,
        "stream": True,
    }
    if system:
        body["system"] = system
    if request.temperature is not None:
        body["temperature"] = request.temperature

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/v1/messages",
            headers={
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    yield "data: [DONE]\n\n"
                    return
                try:
                    event = json.loads(data)
                    if event["type"] == "content_block_delta":
                        delta_text = event["delta"].get("text", "")
                        chunk = {
                            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": request.model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": delta_text},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                    elif event["type"] == "message_stop":
                        yield "data: [DONE]\n\n"
                        return
                except json.JSONDecodeError:
                    continue


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    if request.stream:
        return StreamingResponse(
            stream_anthropic(request), media_type="text/event-stream"
        )

    system, messages = to_anthropic_messages(request.messages)
    model_id = MODEL_ALIASES.get(request.model, request.model)

    body = {
        "model": model_id,
        "messages": messages,
        "max_tokens": request.max_tokens or 4096,
    }
    if system:
        body["system"] = system
    if request.temperature is not None:
        body["temperature"] = request.temperature

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{BASE_URL}/v1/messages",
            headers={
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return to_openai_response(resp.json(), request.model)


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "created": int(time.time()), "owned_by": "anthropic"}
            for m in MODEL_ALIASES.keys()
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "claude-proxy", "models": list(MODEL_ALIASES.keys())}
