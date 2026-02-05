import asyncio
import json
import os
import time
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Claude Code API", version="1.0.0")


class CodeTaskRequest(BaseModel):
    prompt: str
    working_dir: Optional[str] = "/workspace"
    allowed_tools: Optional[list[str]] = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "claude-code"
    messages: list[ChatMessage]
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False


async def run_claude_code(prompt: str, working_dir: str = "/workspace") -> str:
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "text",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
        env={**os.environ, "CLAUDE_CODE_HEADLESS": "1"},
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    output = stdout.decode()
    if proc.returncode != 0 and not output:
        output = f"Error (exit {proc.returncode}): {stderr.decode()}"
    return output


@app.post("/v1/code/execute")
async def execute_code_task(request: CodeTaskRequest):
    result = await run_claude_code(request.prompt, request.working_dir)
    return {
        "id": f"code-{uuid.uuid4().hex[:12]}",
        "status": "completed",
        "output": result,
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    user_messages = [m for m in request.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message provided")

    prompt = user_messages[-1].content
    result = await run_claude_code(prompt)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "claude-code",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "claude-code", "object": "model", "created": int(time.time()), "owned_by": "anthropic"}
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "claude-code", "models": ["claude-code"]}
