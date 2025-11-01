import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      "/analyze": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/healthz": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/watchlist": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/reports": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/macro": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/scanner": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
