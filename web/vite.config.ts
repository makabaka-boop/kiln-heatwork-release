/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 本地开发时把 API 请求转发给 FastAPI
      "/api": "http://localhost:8000",
    },
  },
  preview: {
    port: 8080,
    proxy: {
      // 预览构建产物时同样代理，行为对齐生产 nginx
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
