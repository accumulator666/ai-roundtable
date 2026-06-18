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
    allowed_tools: Optional[list[str]] = ["Edit", "Read", "Glob", "Grep", "Write"]


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "claude-code"
    messages: list[ChatMessage]
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False


async def run_claude_code(prompt: str, working_dir: str = "/workspace", model_flag: list[str] = None, allowed_tools: list[str] = None) -> str:
    cmd = [
        "claude", "-p",
        "--output-format", "text",
    ]
    if model_flag:
        cmd.extend(model_flag)
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
        env={**os.environ, "CLAUDE_CODE_HEADLESS": "1"},
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=prompt.encode()), timeout=300
    )
    output = stdout.decode()
    if proc.returncode != 0 and not output:
        output = f"Error (exit {proc.returncode}): {stderr.decode()}"
    return output


@app.post("/v1/code/execute")
async def execute_code_task(request: CodeTaskRequest):
    result = await run_claude_code(request.prompt, request.working_dir, allowed_tools=request.allowed_tools)
    return {
        "id": f"code-{uuid.uuid4().hex[:12]}",
        "status": "completed",
        "output": result,
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    # Build a full prompt from all messages so Claude Code gets the full context
    parts = []
    for m in request.messages:
        if m.role == "system":
            parts.append(f"<system>\n{m.content}\n</system>")
        elif m.role == "user":
            parts.append(f"User: {m.content}")
        elif m.role == "assistant":
            parts.append(f"Assistant: {m.content}")

    if not parts:
        raise HTTPException(status_code=400, detail="No messages provided")

    prompt = "\n\n".join(parts) + "\n\nRespond as the assistant described in the system prompt above. Be direct and concise."

    # Use the requested model if it's a real Claude model, otherwise default
    model_flag = []
    if request.model and request.model.startswith("claude-") and request.model != "claude-code":
        model_flag = ["--model", request.model]

    result = await run_claude_code(prompt, model_flag=model_flag)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model or "claude-code",
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
