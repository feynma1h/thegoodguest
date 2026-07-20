import type { NextConfig } from "next";

// Static export (decision 0050): no SSR/ISR/API routes — the backend is
// api-public on Cloud Run, and this app deploys as static files to
// Firebase Hosting (`out/` is the hosting public dir; see firebase.json).
const nextConfig: NextConfig = {
  output: "export",
  // next/image's optimizer needs a server; static export serves plain files.
  images: { unoptimized: true },
};

export default nextConfig;
