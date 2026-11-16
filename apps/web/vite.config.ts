import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// VITE_BASE: public path prefix when served behind a path-based proxy,
// e.g. /proxy/5173/ (code-server). Leave unset for plain localhost.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  let base = env.VITE_BASE || "/";
  if (!base.endsWith("/")) base += "/";
  const apiPrefix = `${base}api`;
  return {
    base,
    plugins: [react(), tailwindcss()],
    // shadcn convention: "@/..." = src/... (the chat blocks live in src/registry/blocks/chat).
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    server: {
      port: 5173,
      host: true,
      allowedHosts: ["d1cst9gtm87gj1.cloudfront.net"],
      // Same-origin access to the backend: <base>api/* -> http://localhost:8000/*
      proxy: {
        [apiPrefix]: {
          target: env.BACKEND_URL || "http://localhost:8000",
          ws: true,
          rewrite: (path: string) => path.slice(apiPrefix.length) || "/",
        },
      },
    },
  };
});
