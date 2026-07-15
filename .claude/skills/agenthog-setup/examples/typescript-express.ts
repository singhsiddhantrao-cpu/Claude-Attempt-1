/**
 * Express + AgentHog — minimum complete example.
 *
 * One task_run per request via the agenthog Express middleware. Any fetch /
 * OpenAI / Anthropic call inside the handler becomes a span on the task_run.
 */

import "agenthog/integrations/express";
import "agenthog/integrations/fetch";
// Add others as needed:
// import "agenthog/integrations/openai";
// import "agenthog/integrations/anthropic";

import { init, startTaskRun } from "agenthog";
import express from "express";

// 1. Init before any other instrumentation imports run their side effects.
init({
  apiKey: process.env.AGENTOS_API_KEY!,
  endpoint: process.env.AGENTOS_ENDPOINT ?? "https://api.theagentos.space",
  workspaceId: process.env.AGENTOS_WORKSPACE_ID!,
  agentId: "express-chat",
});

const app = express();
app.use(express.json());

// 2. Wrap the per-request handler in startTaskRun. The express integration
//    above will auto-correlate; explicit wrapping makes the contract obvious.
app.post("/chat", async (req, res) => {
  await startTaskRun(
    { userId: req.body.userId },
    async (ctx) => {
      const reply = await callMyLLM(req.body.message);
      res.json({ reply, traceId: ctx.traceId });
    },
  );
});

async function callMyLLM(message: string): Promise<string> {
  // Replace with your actual LLM call. fetch / openai / anthropic / etc.
  // are auto-instrumented and show up as spans on the task_run.
  return `echo: ${message}`;
}

app.listen(3000, () => console.log("listening on :3000"));
