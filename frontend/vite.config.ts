import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy API calls to the FastAPI backend during development.
      // ws: true upgrades the CRDT collaboration socket (/api/pads/:slug/ws).
      "/api": { target: "http://localhost:8000", ws: true },
      "/health": "http://localhost:8000",
    },
  },
});
