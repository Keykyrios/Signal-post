import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import fs from "node:fs";

// In dev, serve ../out under /data so the app can load profiles.jsonl.
// In production the Python command `signalpost serve` does the same.
function serveOutFolder(): Plugin {
  return {
    name: "serve-out-folder",
    configureServer(server) {
      server.middlewares.use("/data", (req, res, next) => {
        const rel = decodeURIComponent((req.url || "/").split("?")[0]);
        const file = path.join(path.resolve(import.meta.dirname, "../out"), rel);
        if (!file.startsWith(path.resolve(import.meta.dirname, "../out")) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
          return next();
        }
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        fs.createReadStream(file).pipe(res);
      });
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss(), serveOutFolder()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
});
