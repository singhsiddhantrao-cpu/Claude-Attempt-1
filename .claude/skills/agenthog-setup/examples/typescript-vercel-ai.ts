/**
 * Vercel AI SDK + AgentHog — minimum complete example.
 *
 * Works for both Next.js Route Handlers and standalone Node servers using
 * the Vercel AI SDK. One task_run per request, with the Vercel AI streaming
 * call becoming a span.
 */

import "agenthog/integrations/vercelAI";

import { init, startTaskRun } from "agenthog";
import { generateText } from "ai";
import { openai } from "@ai-sdk/openai";

// 1. Init at module load. In Next.js, this file is typically
//    `instrumentation.ts` at the project root.
init({
  apiKey: process.env.AGENTOS_API_KEY!,
  endpoint: process.env.AGENTOS_ENDPOINT ?? "https://api.theagentos.space",
  workspaceId: process.env.AGENTOS_WORKSPACE_ID!,
  agentId: "vercel-ai-chat",
});

// 2. Per-request handler (e.g. POST /api/chat in Next.js).
export async function POST(req: Request): Promise<Response> {
  const { messages, userId } = await req.json();

  return await startTaskRun(
    { userId },
    async (ctx) => {
      const { text } = await generateText({
        model: openai("gpt-4o-mini"),
        messages,
      });

      return Response.json({ text, traceId: ctx.traceId });
    },
  );
}
