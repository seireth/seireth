import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const proxy = {
  target: process.env.SEIRETH_UI_API_URL ?? "http://127.0.0.1:8000",
  changeOrigin: false,
};
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: { proxy: { "/api": proxy, "/health": proxy } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});
