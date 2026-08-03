import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      // src-tauri/target holds Rust build output that Cargo actively
      // writes to (and locks, on Windows) during compilation. Vite's
      // default watcher otherwise tries to observe files in there too
      // and crashes with EBUSY the moment it hits a file Cargo currently
      // has open. This directory is never part of the frontend source,
      // so it should never be watched in the first place.
      ignored: ["**/src-tauri/**"],
    },
  },
  clearScreen: false,
});
