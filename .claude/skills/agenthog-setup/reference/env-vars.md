# AgentHog SDK — environment variables

All SDK variables share the `AGENTOS_` prefix. Both Python and TypeScript SDKs
read the same variables. Explicit args to `init(...)` override env vars.

## Required (at least one path)

| Var | Purpose | Example |
|---|---|---|
| `AGENTOS_API_KEY` | Authenticates the SDK to ingestion. Get it from Settings → API Keys in the dashboard. | `agops_a1b2c3d4...` |
| `AGENTOS_WORKSPACE_ID` | Tenancy boundary. Get it from the top-right of the dashboard. | `ws_94QkR8mN...` (UUID) |

Setting both via env is the recommended path for production deploys.
Passing them inline to `init(...)` is fine for scripts.

**Python: `agenthog init`** (requires `agenthog >= 0.5.0`) is the quickest way
to set the two required values locally — it prompts for them and writes a
gitignored `.env` (the key is entered by the user, never handled by the coding
agent). For production, prefer real environment variables or a secret manager.

## Optional

| Var | Default | Purpose |
|---|---|---|
| `AGENTOS_ENDPOINT` | `https://api.theagentos.space` | Override for self-hosted / staging. |
| `AGENTOS_AGENT_ID` | `null` | Descriptive label per service. Helps group traces in the UI. |
| `AGENTOS_ENV` | `null` | Environment tag (`prod`, `staging`, `dev`). Surfaces in the UI as a filter. |
| `AGENTOS_DISABLE` | `0` | Set to `1`/`true` to make all SDK calls no-ops. Useful in CI / tests. |

## Deprecated (still read in 0.2.0 — emits a warning)

| Var | Replacement | Notes |
|---|---|---|
| `AGENTOS_PROJECT_ID` | `AGENTOS_WORKSPACE_ID` | Renamed May 2026. Old var is still read with a one-time DeprecationWarning (Python) or `console.warn` (TS). |

## Runtime-only

If your service is deployed via AgentRun (the AgentOS runtime), AgentRun
injects these automatically — you don't set them by hand:

| Var | Set by AgentRun |
|---|---|
| `AGENTOS_RUNTIME` | `1` |
| `AGENTOS_RUNTIME_SOCKET` | Path to the sidecar Unix socket. |

When `AGENTOS_RUNTIME=1`, the SDK routes ingestion through the local sidecar
instead of direct HTTPS, which lets AgentRun mediate every event (policy
enforcement, syscall mediator, replay capture).

## Recommended `.env.example`

```dotenv
# AgentHog — observability for AI agents (https://theagentos.space)
AGENTOS_API_KEY=agops_replace_me
AGENTOS_WORKSPACE_ID=ws_replace_me

# Optional
AGENTOS_ENDPOINT=https://api.theagentos.space
AGENTOS_AGENT_ID=my-service
AGENTOS_ENV=dev
# AGENTOS_DISABLE=1  # uncomment to silence the SDK locally
```

Add `.env` to `.gitignore` (most projects already do).
