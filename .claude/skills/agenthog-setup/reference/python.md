# AgentHog Python SDK — reference

Companion reference for the `agenthog-setup` skill. Canonical source:
https://github.com/TheAgentOS/agentos-python

## Install

```bash
pip install agenthog
# or, with extras:
pip install 'agenthog[openai]'         # OpenAI auto-instrumentation
pip install 'agenthog[anthropic]'      # Anthropic auto-instrumentation
pip install 'agenthog[langchain]'      # LangChain / LangGraph auto-instrumentation
pip install 'agenthog[otel]'           # OpenTelemetry passthrough
pip install 'agenthog[audit]'          # Offline audit ledger verifier CLI
pip install 'agenthog[all]'            # Everything
```

Requires Python 3.10+.

## `agenthog.init(...)`

Construct and register the global default client. Call once at app startup.

```python
agenthog.init(
    api_key: str | None = None,        # AGENTOS_API_KEY env var if None
    *,
    endpoint: str | None = None,       # AGENTOS_ENDPOINT or https://api.theagentos.space
    environment: str | None = None,    # AGENTOS_ENV (e.g. "prod", "staging")
    capture_content: bool | None = None,  # default True; set False to redact prompt/response bodies
    flush_interval_ms: int | None = None, # default 250
    flush_batch_size: int | None = None,  # default 100
    buffer_max_size: int | None = None,   # default 10_000
    disable: bool | None = None,       # AGENTOS_DISABLE; true silences all calls
    agent_id: str | None = None,       # AGENTOS_AGENT_ID; descriptive label per service
    workspace_id: str | None = None,   # AGENTOS_WORKSPACE_ID
    kind: str = "sync",                # "sync" or "async" — async returns AsyncClient
)
```

Re-calling `init` replaces the default; shut down the previous client first
if you need clean state.

## Tracing primitives

### `start_task_run` — context manager

Wrap one end-to-end execution. Each call = one `task_run_id`.

```python
with agenthog.start_task_run(
    agent_id: str | None = None,        # override the global default for this run
    task_run_id: str | None = None,     # provide your own ID; auto-generated otherwise
    trace_id: str | None = None,        # W3C trace context inbound
    user_id: str | None = None,         # attribute the run to a specific user
    session_id: str | None = None,      # group runs into a conversation
) as ctx:
    # ctx.task_run_id, ctx.trace_id, ctx.span_id available
    ...
```

Note: there is no `metadata=` kwarg. Attach identifiers via the explicit
kwargs above (`user_id`, `session_id`, `agent_id`, etc.).

### `start_span` — nest spans inside a task run

Signature is `start_span(name, kind="internal")`. It yields an
`IdentityContext` (carrying `trace_id` / `span_id` / `task_run_id`), **not** an
OpenTelemetry span — there is no `attributes=` kwarg and no `set_attribute()`
method. To record detail for the work inside a span, emit a typed event with
one of the `log_*` helpers below (or a raw `agenthog.emit(...)`):

```python
with agenthog.start_span(name="retrieve_docs", kind="internal"):
    docs = retrieve(query)
    agenthog.get_default_client().log_tool_call(
        name="retrieve_docs", input={"k": 5}, output={"doc_count": len(docs)}
    )
```

## Auto-instrumentation

```python
agenthog.autoinstrument(
    only=None,    # list[str] of specific integrations to install
    skip=None,    # list[str] of integrations to skip
    client=None,  # pin to a non-default client (rare)
)
# Returns the list of installed integration names.
```

Detects installed packages and patches in: `openai`, `anthropic`,
`langchain` (and `langgraph` via langchain-core). As of `0.8.0` it also ingests
OpenInference / OTel spans, and captures raw-HTTP OpenAI-compatible calls.

## Tracing custom tools

`autoinstrument` captures LLM calls; a hand-written agent's *tools* are ordinary
functions and need marking. Two ways, both emit an `agent.tool_call` step under
the active `task_run`:

```python
# Per function — @agenthog.tool (>= 0.7.0)
@agenthog.tool
def get_weather(city: str) -> dict: ...

# Whole tools module in one call — instrument_module (>= 0.9.0). Wraps every
# public function defined in the module and RETURNS the names wrapped, so you
# can assert the trace shows that many tool steps (nothing silently missed).
import weather
wrapped = agenthog.instrument_module(weather)   # ['get_weather', 'geocode', ...]
```

`instrument_module` skips private helpers (leading `_`), imported names,
classes, and constants; override with `include=[...]` / `exclude=[...]`. It
reuses `@tool`, so already-decorated functions are never double-wrapped.

## Manual logging

When auto-instrumentation isn't possible (custom LLM client, or **tool calls in
a hand-written agent loop** — the common case), log events directly. Available
helpers on the client: `log_llm_call`, `log_tool_call`, `log_eval`,
`log_business_event`, `log_flag_check`, `log_security_alert`, `log_handoff`,
`log_retrieval`.

```python
client = agenthog.get_default_client()

# Record each tool the agent invokes, so it shows as a tool_call step in the
# trace. Without this, raw (non-framework) tool calls are invisible and evals
# can wrongly conclude "the agent never used a tool."
client.log_tool_call(
    name="lookup_order",
    input={"order_id": "ORD-1002"},
    output={"status": "shipped"},
)
client.log_business_event(name="checkout_completed", revenue=49.99)
client.log_eval(name="hallucination_score", score=0.12)
```

> `autoinstrument` covers `openai`/`anthropic`/`langchain` LLM calls — and
> LangChain/LangGraph tool nodes — but **not** tool calls you make in a plain
> OpenAI/Anthropic loop; those need an explicit `log_tool_call`.

## Feature flags & experiments

Two ways to record flag/experiment evaluations:

**1. Let AgentHog resolve the flag — `client.flag(key, default, **context)`.**
Evaluates against flag definitions polled from `GET /v1/flags` (cached, refreshed
every 60s; local first-match-wins rule eval with percentage rollout + variants),
returns the resolved value, and **auto-emits** an `agent.flag_check`:

```python
client = agenthog.get_default_client()
model = client.flag("model-routing", default="gpt-4o-mini", user_id=user_id)
```

**2. Record an externally-resolved flag — `client.log_flag_check(...)`.**
Use when your own system (LaunchDarkly, Statsig, config) decides the value and
you just want it in the trace:

```python
client.log_flag_check(
    "new-prompt-v2",            # flag key
    True,                        # resolved value
    variant="treatment",
    experiment_id="exp-42",
    reason="rule_match",         # one of: default | rule_match | percentage_rollout
)
```

Both emit `agent.flag_check` with `flag.key` / `flag.value` / `flag.variant` /
`flag.experiment_id` / `flag.reason`, so the dashboard can slice metrics by
experiment arm.

## Failure-mode contract

The SDK guarantees no public method raises. Errors are routed to the internal
`agenthog.sdk` logger (Python's `logging` module, namespace
`agenthog.sdk.{transport,ingest,init,...}`).

To surface SDK errors during local dev:

```python
import logging
logging.getLogger("agenthog.sdk").setLevel(logging.DEBUG)
```

## Shutdown

```python
agenthog.shutdown()  # blocking flush, called at app teardown
```

Or per-client: `client.shutdown()`. The sync client also flushes on
`atexit` automatically.

## Environment variables

See [`env-vars.md`](./env-vars.md) for the full list.

## Privacy controls

```python
agenthog.init(..., capture_content=False)
```

When `capture_content=False`, the SDK records call metadata (latency, token
counts, model name) but redacts prompt/response bodies. Use this for
projects under PII / HIPAA constraints.

## Versioning

SemVer with 0.x policy: minor bumps may break; patch bumps are safe. The 0.1.4
release added deprecation aliases for the `project_id → workspace_id` rename;
as of 0.2.0 the aliases are **still read** but emit a one-time
`DeprecationWarning` (removal deferred to a later release).

See https://github.com/TheAgentOS/agentos-python/blob/main/CHANGELOG.md
