import type { NextConfig } from "next";

// Server-side address of the FastAPI service. The browser never calls it directly:
// requests to /api/* are proxied same-origin so the session cookie stays first-party.
const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiInternalUrl}/:path*` }];
  },
};

export default nextConfig;
