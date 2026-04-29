import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

// Optional HTTPS for local-network device testing (camera/geolocation
// require a secure context). Drop mkcert-generated certs as
// `frontend/localhost+<n>.pem` + `frontend/localhost+<n>-key.pem` and
// vite picks them up automatically. Otherwise serves HTTP.
// Resolves relative to this config file so it works regardless of
// the directory vite is invoked from.
const here = path.dirname(fileURLToPath(import.meta.url));
const certFile = fs.readdirSync(here).find((f: string) => /^localhost\+\d+\.pem$/.test(f));
const keyFile = fs.readdirSync(here).find((f: string) => /^localhost\+\d+-key\.pem$/.test(f));
const https = certFile && keyFile
  ? {
      key: fs.readFileSync(path.join(here, keyFile)),
      cert: fs.readFileSync(path.join(here, certFile)),
    }
  : undefined;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { "/api": "http://localhost:8000" },
    hmr: { host: "localhost" },
    ...(https ? { https, allowedHosts: true } : {}),
  },
});
