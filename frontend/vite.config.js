import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on uvicorn (port 8000); in production FastAPI serves dist/ itself.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
