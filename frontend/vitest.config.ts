import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  esbuild: { jsx: "automatic" },
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  test: { environment: "jsdom", include: ["tests/unit/**/*.test.{ts,tsx}"], setupFiles: ["tests/unit/setup.ts"] },
});
