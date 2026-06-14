import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// HCT Lab site. Reads Supabase directly in the browser with the publishable
// (read-only) key — no backend API. Config comes from VITE_SB_* env vars.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
