import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const proxy = {
  target: process.env.SEIRETH_UI_API_URL ?? "http://127.0.0.1:8000",
  changeOrigin: false,
};
export default defineConfig({
  base: "/dashboard/",
  plugins: [react()],
  server: { proxy: { "/api": proxy, "/health": proxy } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "lcovonly"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/**/*.d.ts"],
    },
  },
});
