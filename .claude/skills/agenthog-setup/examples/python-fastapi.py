"""FastAPI + AgentHog — minimum complete example.

Mounts AgentHog tracing as the first thing the app does. Every request to
/chat becomes one task_run with its LLM/tool calls nested inside.
"""

from __future__ import annotations

import os

import agenthog
from fastapi import FastAPI
from pydantic import BaseModel

# 1. Init at module load — before FastAPI() is constructed.
agenthog.init(
    api_key=os.environ["AGENTOS_API_KEY"],
    endpoint=os.environ.get("AGENTOS_ENDPOINT", "https://api.theagentos.space"),
    workspace_id=os.environ["AGENTOS_WORKSPACE_ID"],
    agent_id="fastapi-chat",
)

# 2. Auto-instrument any installed LLM SDK (openai / anthropic / langchain).
#    Idempotent — safe to call even when no extras are installed.
agenthog.autoinstrument()

app = FastAPI()


class ChatRequest(BaseModel):
    user_id: str
    message: str


@app.post("/chat")
async def chat(req: ChatRequest) -> dict[str, str]:
    # 3. Wrap the per-request loop. Everything inside this with-block becomes
    #    one task_run; LLM calls auto-instrumented above become spans on it.
    with agenthog.start_task_run(user_id=req.user_id) as ctx:
        # ... your agent logic here. Example placeholder:
        reply = await call_my_llm(req.message)
        return {"reply": reply, "trace_id": ctx.trace_id}


async def call_my_llm(message: str) -> str:
    # Replace with your actual LLM call. Anything from openai / anthropic /
    # langchain shows up as a span on the task_run automatically.
    return "echo: " + message
