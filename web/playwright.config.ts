import { defineConfig, devices } from "@playwright/test";

/**
 * 真实联调：默认打向 Docker Compose 暴露的 web 服务（nginx -> api），
 * 也可用 PLAYWRIGHT_BASE_URL 指向本地开发服务器。
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:8080",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
