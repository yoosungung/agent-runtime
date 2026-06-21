import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const envoyProxyTarget =
    env.VITE_DEV_ENVOY_PROXY_TARGET || "http://127.0.0.1:8084";

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: "http://localhost:8000",
          changeOrigin: true,
          // NO rewrite - keep /api prefix
        },
        "/v1/agents": {
          target: envoyProxyTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
