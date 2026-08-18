import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

// P1.11 — Config Vitest manquante, signalée par l'audit "Ready to Go
// Enterprise" comme un des 5 points à corriger avant un GO strict.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.{test,spec}.{js,jsx,ts,tsx}"],
    // setup.ts et les tests de src/tests/ viennent de V28.2.8-AUDITED —
    // pas encore exécutés contre cette base (voir MERGE_NOTES.md).
    setupFiles: ["./src/tests/setup.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
