import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built assets go to dist/ and are served by stock_service.py (FastAPI).
// In dev (`npm run dev`), /api is proxied to the backend on :7779.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:7779",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
