import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev`: the browser calls /api, Vite forwards it to the API on port 8000 (same as nginx in Docker).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": { target: "http://localhost:8000", rewrite: (p) => p.replace(/^\/api/, "") } } },
});
