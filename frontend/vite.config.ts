import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard talks to the FastAPI backend directly (CORS allows this origin).
// Port 5173 is fixed so it matches the backend's CORS_ORIGINS default.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
});
