// One ES module (flow.js) and its lazily loaded parts (the editor's icons) under chunks/, plus flow.css: the app imports
// /static/vendor/flow/flow.js only when the template editor opens.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  base: "./",
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    cssCodeSplit: false,
    chunkSizeWarningLimit: 4096,
    rollupOptions: {
      input: "src/main.jsx",
      preserveEntrySignatures: "exports-only",
      output: {
        entryFileNames: "flow.js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: (a) => (a.names?.[0] || a.name || "").endsWith(".css") ? "flow.css" : "assets/[name]-[hash][extname]",
      },
    },
  },
});
