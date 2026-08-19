// Vite config: React plugin + a dev proxy so `npm run dev` (port 5173) can call
// the Django API on port 8000 without CORS headaches. In Docker, nginx does the
// proxying instead (see nginx.conf), and the app always calls the relative "/api".
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
