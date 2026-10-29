import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

const API = process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: { port: 5173, proxy: { "/api": { target: API, changeOrigin: false } } },
  preview: { port: 4173, proxy: { "/api": { target: API, changeOrigin: false } } },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          if (id.includes("recharts") || id.includes("d3-")) return "charts";
          if (id.includes("node_modules/react") || id.includes("react-router")) return "react";
          return undefined;
        },
      },
    },
  },
});
