import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  // Vite 8 transforms with Oxc, not esbuild (the `esbuild` option no longer accepts `jsx`). Keep the automatic JSX
  // runtime, matching "jsx": "react-jsx" in tsconfig.app.json and @vitejs/plugin-react in the app build.
  oxc: { jsx: { runtime: "automatic" } },
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  test: { environment: "jsdom", include: ["tests/unit/**/*.test.{ts,tsx}"], setupFiles: ["tests/unit/setup.ts"] },
});
