/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    // Tests never reach a backend: every fetch is stubbed per test, and an
    // unstubbed call fails loudly rather than hitting localhost:8000.
    restoreMocks: true,
  },
});
