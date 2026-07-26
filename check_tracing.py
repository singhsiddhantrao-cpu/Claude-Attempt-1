"""Diagnose why traces aren't reaching theagentos.space.

Run it from the project folder with the venv active:

    python check_tracing.py

It checks, in order:
  1. that .env is found and which provider/tracing keys are set,
  2. that this copy of the project actually contains the explicit-tracing code,
  3. that the agenthog SDK initializes,
  4. that a real test event can be sent -- and reports the HTTP result.

Nothing here calls a model, so it costs nothing and needs no provider credit.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def bad(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def info(msg: str) -> None:
    print(f"         {msg}")


def mask(value: str) -> str:
    """Show enough of a key to identify it without printing the secret."""
    if len(value) <= 12:
        return f"{value[:3]}...({len(value)} chars)"
    return f"{value[:7]}...{value[-4:]} ({len(value)} chars)"


print("=" * 62)
print(" theagentos.space tracing diagnostic")
print("=" * 62)

# --- 1. .env ---------------------------------------------------------------
print("\n1. Environment file")
env_path = HERE / ".env"
if not env_path.is_file():
    bad(f"No .env file found at {env_path}")
    info("Run run.bat once to create it, or copy .env.example to .env.")
    sys.exit(1)
ok(f".env found at {env_path}")

try:
    from dotenv import load_dotenv
except ImportError:
    bad("python-dotenv is not installed -- is the virtualenv active?")
    sys.exit(1)

load_dotenv(env_path)

# Warn about a duplicated key line, which silently overrides the good value.
seen: dict[str, int] = {}
for line in env_path.read_text(errors="replace").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        name = line.split("=", 1)[0].strip()
        seen[name] = seen.get(name, 0) + 1
for name, count in seen.items():
    if count > 1:
        bad(f"{name} appears {count} times in .env -- the LAST one wins. Delete the extras.")

agentos_key = os.getenv("AGENTOS_API_KEY", "")
agent_id = os.getenv("AGENTOS_AGENT_ID", "")

if agentos_key:
    ok(f"AGENTOS_API_KEY is set: {mask(agentos_key)}")
    if agentos_key != agentos_key.strip():
        bad("...but it has leading/trailing whitespace -- remove it.")
else:
    bad("AGENTOS_API_KEY is NOT set -- tracing is disabled entirely.")
    info("Add it to .env, then re-run this script.")
    sys.exit(1)

if agent_id:
    ok(f"AGENTOS_AGENT_ID is set: '{agent_id}'")
    info("This must match an agent that exists on theagentos.space dashboard,")
    info("and the dashboard's 'Any agent' filter must not exclude it.")
else:
    info("AGENTOS_AGENT_ID not set -- the app will default to 'stock-analysis'.")

provider = next(
    (
        n
        for n in ("GROQ_API_KEY", "GOOGLE_API_KEY", "NVIDIA_API_KEY", "ANTHROPIC_API_KEY")
        if os.getenv(n)
    ),
    None,
)
if provider:
    ok(f"Model provider key present: {provider}")
else:
    bad("No model provider key set -- analyses can't run, so nothing would be traced.")

# --- 2. Is this copy of the code the fixed one? ----------------------------
print("\n2. Project code version")
service = HERE / "stock_service.py"
if not service.is_file():
    bad("stock_service.py not found -- run this from the project folder.")
    sys.exit(1)
source = service.read_text(errors="replace")
if "_trace_llm_call" in source:
    ok("stock_service.py contains the explicit-tracing code.")
else:
    bad("stock_service.py is an OLD version WITHOUT explicit tracing.")
    info("This is the usual reason traces never appear on Groq.")
    info("Download the latest project files and replace stock_service.py.")

# --- 3. SDK ----------------------------------------------------------------
print("\n3. agenthog SDK")
try:
    import agenthog
except ImportError:
    bad("agenthog is not installed. Install with: pip install 'agenthog[anthropic]'")
    sys.exit(1)
ok(f"agenthog imported (version {getattr(agenthog, '__version__', 'unknown')})")

try:
    agenthog.init(agent_id=agent_id or "stock-analysis")
    ok("agenthog.init() succeeded")
except Exception as exc:
    bad(f"agenthog.init() failed: {exc}")
    sys.exit(1)

client = agenthog.get_default_client()
endpoint = getattr(getattr(client, "config", None), "endpoint", "https://api.theagentos.space")
info(f"Sending to endpoint: {endpoint}")

# Surface the SDK's own warnings (auth failures, dropped batches). They are
# logged but invisible by default, which is why a bad key looks like silence.
import logging

logging.basicConfig(level=logging.WARNING, format="         [sdk] %(message)s")
logging.getLogger("agenthog").setLevel(logging.WARNING)

# --- 4. Does the server accept this API key? -------------------------------
print("\n4. Checking the API key against the server")
try:
    import httpx

    resp = httpx.post(
        f"{endpoint.rstrip('/')}/v1/events/batch",
        headers={
            "Authorization": f"Bearer {agentos_key}",
            "Content-Type": "application/json",
        },
        json={"events": []},
        timeout=20.0,
    )
    if resp.status_code in (200, 202, 204):
        ok(f"Server accepted the key (HTTP {resp.status_code})")
    elif resp.status_code in (401, 403):
        bad(f"Server REJECTED the key (HTTP {resp.status_code}) -- this is the problem.")
        info("Generate a fresh key on theagentos.space and update AGENTOS_API_KEY.")
        info(f"Response: {resp.text[:200]}")
    else:
        info(f"Unexpected HTTP {resp.status_code}: {resp.text[:200]}")
        info("(An empty batch may not be a valid request for this API; if the")
        info(" test event below shows up on the dashboard, ignore this.)")
except Exception as exc:
    bad(f"Could not reach {endpoint}: {exc}")
    info("Check your internet connection, VPN, or corporate proxy.")

# --- 5. Send a real test event ---------------------------------------------
print("\n5. Sending a test trace")
try:
    with agenthog.start_task_run(agent_id=agent_id or "stock-analysis"):
        client.log_llm_call(
            model="diagnostic-test",
            system="diagnostic",
            input=[{"role": "user", "content": "tracing diagnostic"}],
            output=[{"role": "assistant", "content": "hello from check_tracing.py"}],
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            duration_ms=1.0,
        )
    ok("Test event queued")
except Exception as exc:
    bad(f"Could not queue the event: {exc}")
    sys.exit(1)

try:
    agenthog.flush()
    ok("flush() completed without error")
except Exception as exc:
    bad(f"flush() raised: {exc}")

try:
    agenthog.shutdown()
except Exception:
    pass

print("\n" + "=" * 62)
print("Done. Now open theagentos.space and look for a trace whose model is")
print("'diagnostic-test'.")
print()
print("  - If you SEE it: the connection works. Traces from real runs will")
print("    appear too -- make sure an analysis actually completes (a failing")
print("    model call means there is nothing to trace).")
print("  - If you DON'T see it: check that the API key is valid for that")
print("    workspace, that AGENTOS_AGENT_ID matches an agent on the dashboard,")
print("    and that the dashboard's time-range filter covers 'now'.")
print("=" * 62)
