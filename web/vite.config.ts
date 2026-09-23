import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Em desenvolvimento o Vite encaminha /api para a FastAPI (mesma origem para o navegador).
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
});
