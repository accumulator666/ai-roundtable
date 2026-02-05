import os
import json
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import time
import uuid

app = FastAPI(title="Gemini Proxy", version="1.0.0")

API_KEY = os.environ.get("GOOGLE_API_KEY", "")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
AVAILABLE_MODELS = ["gemini-2.0-flash", "gemini-2.0-pro", "gemini-1.5-pro"]
MODEL_MAP = {
    "gemini-2.0-flash": "models/gemini-2.0-flash",
    "gemini-2.0-pro": "models/gemini-2.0-pro",
    "gemini-1.5-pro": "models/gemini-1.5-pro",
}


class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatRequest(BaseModel):
    model: str = "gemini-2.0-flash"
    messages: list[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 4096
    stream: Optional[bool] = False


def to_gemini_contents(messages: list[ChatMessage]) -> tuple[Optional[str], list[dict]]:
    system_instruction = None
    contents = []
    for msg in messages:
        if msg.role == "system":
            system_instruction = msg.content
        else:
            role = "user" if msg.role == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg.content}]})
    return system_instruction, contents


def to_openai_response(gemini_resp: dict, model: str) -> dict:
    content = ""
    candidates = gemini_resp.get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        content = "".join(p.get("text", "") for p in parts)

    usage_meta = gemini_resp.get("usageMetadata", {})
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": usage_meta.get("promptTokenCount", 0),
            "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
            "total_tokens": usage_meta.get("totalTokenCount", 0),
        },
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY not set")

    gemini_model = MODEL_MAP.get(request.model, f"models/{request.model}")
    system_instruction, contents = to_gemini_contents(request.messages)

    body = {
        "contents": contents,
        "generationConfig": {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_tokens or 4096,
        },
    }
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    if request.stream:
        async def stream_gemini():
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{BASE_URL}/{gemini_model}:streamGenerateContent?alt=sse&key={API_KEY}",
                    json=body,
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        try:
                            event = json.loads(data)
                            candidates = event.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                text = "".join(p.get("text", "") for p in parts)
                                chunk = {
                                    "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": request.model,
                                    "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                                }
                                yield f"data: {json.dumps(chunk)}\n\n"
                        except json.JSONDecodeError:
                            continue
                    yield "data: [DONE]\n\n"

        return StreamingResponse(stream_gemini(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{BASE_URL}/{gemini_model}:generateContent?key={API_KEY}",
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
            {"id": m, "object": "model", "created": int(time.time()), "owned_by": "google"}
            for m in AVAILABLE_MODELS
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gemini-proxy", "models": AVAILABLE_MODELS}
