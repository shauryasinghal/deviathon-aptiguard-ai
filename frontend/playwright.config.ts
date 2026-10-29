import { defineConfig } from "@playwright/test";

// Hermetic E2E: a dedicated SQLite DB is migrated + seeded (synthetic, seed 107) and served on separate ports,
// so the developer's working database is never touched.
const E2E_DB = process.env.E2E_DB ?? "/tmp/aptiguard-e2e.db";
const API_PORT = 8001;
const WEB_PORT = 5174;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1, // journeys share one seeded database and run in order
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: `http://localhost:${WEB_PORT}`, trace: "retain-on-failure", viewport: { width: 1440, height: 900 } },
  webServer: [
    {
      command: `rm -f ${E2E_DB} ${E2E_DB}-wal ${E2E_DB}-shm && DATABASE_URL=sqlite:///${E2E_DB} CORS_ORIGINS=http://localhost:${WEB_PORT} ../backend/.venv/bin/python ../scripts/seed_demo.py && DATABASE_URL=sqlite:///${E2E_DB} CORS_ORIGINS=http://localhost:${WEB_PORT} ../backend/.venv/bin/uvicorn app.main:app --app-dir ../backend --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      timeout: 180_000,
      reuseExistingServer: false,
    },
    {
      command: `VITE_API_PROXY=http://127.0.0.1:${API_PORT} npx vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
