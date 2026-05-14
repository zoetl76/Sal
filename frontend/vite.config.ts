import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist" },
  // HTTPS requis pour Telegram Mini App en production
  server: { port: 5173, https: false },
});
