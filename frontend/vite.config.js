import { defineConfig } from "vite";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  server: {
    proxy: {
      "/api": {
        target: process.env.BACKEND_PROXY_TARGET || "http://127.0.0.1:5000",
        changeOrigin: false,
      },
    },
  },
});
