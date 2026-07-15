# AgentHog TypeScript SDK — reference

Companion reference for the `agenthog-setup` skill. Canonical source:
https://github.com/TheAgentOS/agentos-js

## Install

```bash
pnpm add agenthog
# or
npm install agenthog
# or
yarn add agenthog
# or
bun add agenthog
```

Requires Node 18+.

## `init({...})`

```ts
import { init } from "agenthog";

const client = init({
  apiKey?: string,             // AGENTOS_API_KEY env var if omitted
  endpoint?: string,           // AGENTOS_ENDPOINT or default
  environment?: string,        // AGENTOS_ENV
  agentId?: string,            // AGENTOS_AGENT_ID
  workspaceId?: string,        // AGENTOS_WORKSPACE_ID
  captureContent?: boolean,    // default true
  flushIntervalMs?: number,    // default 250
  flushBatchSize?: number,     // default 100
  bufferMaxSize?: number,      // default 10_000
  disable?: boolean,           // AGENTOS_DISABLE
});
```

Returns a `Client`. Also stored as the module-level default, so module-level
helpers (`startTaskRun`, `shutdown`, `flush`) work without passing it.

## Tracing primitives

### `startTaskRun` — async callback

```ts
import { startTaskRun } from "agenthog";

await startTaskRun(
  {
    agentId?: string,
    taskRunId?: string,
    traceId?: string,
    userId?: string,
    sessionId?: string,
  },
  async (ctx) => {
    // ctx.taskRunId, ctx.traceId, ctx.spanId available
    return await runAgent();
  },
);
```

Note: `StartTaskRunArgs` has no `metadata` field — attach identifiers via
`userId`, `sessionId`, `agentId`, etc.

Why callback vs. context manager (Python's `with`): JS lacks RAII, so the
callback form is the most reliable way to guarantee the run gets closed
even when the user's code throws.

### `startSpan`

`StartSpanArgs` is `{ name?, kind? }` — there is **no** `attributes` field, and
the `ctx` passed to the callback is an `IdentityContext` with **no**
`setAttribute()`. Record detail with a `log*` helper (or raw `emit`) instead:

```ts
import { startSpan, getDefaultClient } from "agenthog";

await startSpan({ name: "retrieve_docs", kind: "internal" }, async (ctx) => {
  const docs = await retrieve(query);
  await getDefaultClient()!.logToolCall({
    name: "retrieve_docs",
    input: { k: 5 },
    output: { docCount: docs.length },
  });
  return docs;
});
```

## Per-integration auto-instrumentation

Import the wrapper for the LLM library you use. Side-effect imports patch
the global module:

```ts
import "agenthog/integrations/openai";
import "agenthog/integrations/anthropic";
import "agenthog/integrations/vercelAI";
import "agenthog/integrations/langchain";
import "agenthog/integrations/fetch";       // generic HTTP middleware
import "agenthog/integrations/express";     // Express request middleware
import "agenthog/integrations/opentelemetry"; // OTel passthrough
```

Each integration is a side-effect import that hooks into the underlying SDK
once `init` has been called. Order: call `init` first, then add the imports
near the top of your entrypoint.

## Manual logging

```ts
import { getDefaultClient } from "agenthog";
const client = getDefaultClient()!;

// Record each tool the agent invokes (raw, non-framework tool calls are not
// auto-instrumented — without this they don't appear as tool_call steps).
await client.logToolCall({ name: "lookup_order", input: { orderId: "ORD-1002" }, output: { status: "shipped" } });
await client.logBusinessEvent({ name: "checkout_completed", revenue: 49.99 });
await client.logEval({ name: "hallucination_score", score: 0.12 });
```

Helpers on the client: `logLlmCall`, `logToolCall`, `logEval`,
`logBusinessEvent`, `logFlagCheck`, `logSecurityAlert`, `logHandoff`,
`logRetrieval`.

## Feature flags & experiments

Two ways to record flag/experiment evaluations:

**1. Let AgentHog resolve the flag — `flag(key, default, context?)`.**
Evaluates against definitions polled from `GET /v1/flags` (cached, refreshed
every 60s; first-match-wins rules with percentage rollout + variants), returns
the value, and **auto-emits** `agent.flag_check`:

```ts
import { flag } from "agenthog";
const model = await flag("model-routing", "gpt-4o-mini", { userId });
```

**2. Record an externally-resolved flag — `client.logFlagCheck(...)`.**
Use when your own system (LaunchDarkly, Statsig, config) decides the value:

```ts
await client.logFlagCheck({
  key: "new-prompt-v2",
  value: true,
  variant: "treatment",
  experimentId: "exp-42",
  reason: "rule_match", // one of: default | rule_match | percentage_rollout
});
```

Both emit `agent.flag_check` with `flag.key` / `flag.value` / `flag.variant` /
`flag.experiment_id` / `flag.reason`, so the dashboard can slice by experiment arm.

## Failure-mode contract

The SDK guarantees no public method throws. Errors route to a structured
logger emitting on stderr with the `[agenthog.sdk]` prefix.

To get verbose SDK logs during local dev:

```ts
process.env.AGENTOS_LOG_LEVEL = "debug";
```

## Shutdown

```ts
import { shutdown } from "agenthog";
await shutdown();  // flushes buffered events; call on process exit
```

For long-running servers, the SDK auto-flushes on the `beforeExit` and
`SIGTERM` events. Manual `shutdown()` is mainly for tests and CLI tools.

## W3C trace context

The TS SDK reads and writes the `traceparent` header automatically when the
`fetch` integration is loaded. Pass the inbound `traceparent` to
`startTaskRun({ traceId })` if you need to join an upstream distributed trace.

## OpenTelemetry passthrough

The `opentelemetry` integration registers AgentHog as an OTel span exporter,
so existing OTel-instrumented libraries (Fastify, Hono, NestJS) emit through
AgentHog without any extra wiring beyond the import.

## Environment variables

See [`env-vars.md`](./env-vars.md).

## Versioning

SemVer with 0.x policy. The 0.1.5 release added deprecation aliases for the
`project_id → workspace_id` rename; aliases are scheduled for removal in 0.2.0.

See https://github.com/TheAgentOS/agentos-js/blob/main/CHANGELOG.md
