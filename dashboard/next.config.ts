import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Fully static SPA served by `devpilot dashboard` from the same origin as the API.
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
