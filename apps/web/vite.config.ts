import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  plugins: [react()],
  envDir: "../..",
  build: {
    // The desktop app loads the renderer over file://. Vite's default
    // module-preload polyfill resolves dynamic-import URLs against an http(s)
    // origin and fails under file://, which made the lazily-imported Live2D
    // Cubism4 runtime ("Failed to fetch dynamically imported module:
    // cubism4.es-*.js") never load — the avatar fell back to the placeholder.
    // Disabling the polyfill lets dynamic import() resolve via plain relative
    // paths (base: "./"), which file:// handles correctly.
    modulePreload: { polyfill: false },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
});
