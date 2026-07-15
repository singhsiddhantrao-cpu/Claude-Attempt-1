"""LangGraph + AgentHog — minimum complete example.

LangGraph's per-node execution shows up as nested spans inside one task_run,
giving you a clean graph-walk view in the AgentHog trace viewer.
"""

from __future__ import annotations

import os

import agenthog
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

# 1. Init before any LangGraph / LangChain imports start firing. autoinstrument()
#    detects langchain-core and patches in the AgentHog callback handler.
agenthog.init(
    api_key=os.environ["AGENTOS_API_KEY"],
    endpoint=os.environ.get("AGENTOS_ENDPOINT", "https://api.theagentos.space"),
    workspace_id=os.environ["AGENTOS_WORKSPACE_ID"],
    agent_id="langgraph-research-agent",
)
agenthog.autoinstrument()


# 2. Define your graph — exactly as you would without AgentHog. The
#    autoinstrument() call above hooks the langchain-core callback bus, so
#    every node invocation becomes a span automatically.
def planner(state: dict) -> dict:
    return {"plan": "search then summarize"}


def searcher(state: dict) -> dict:
    return {"results": ["doc1", "doc2"]}


def summarizer(state: dict) -> dict:
    return {"summary": "TL;DR of " + ",".join(state["results"])}


graph = StateGraph(dict)
graph.add_node("planner", planner)
graph.add_node("searcher", searcher)
graph.add_node("summarizer", summarizer)
graph.set_entry_point("planner")
graph.add_edge("planner", "searcher")
graph.add_edge("searcher", "summarizer")
graph.add_edge("summarizer", END)
app = graph.compile()


def run(user_message: str, user_id: str = "anonymous") -> dict:
    # 3. Wrap the graph invocation — one task_run per end-to-end user request.
    #    Use user_id to attribute; session_id to group into conversations.
    with agenthog.start_task_run(user_id=user_id):
        return app.invoke({"messages": [HumanMessage(user_message)]})


if __name__ == "__main__":
    print(run("Summarize the latest AgentOS release"))
    agenthog.shutdown()
