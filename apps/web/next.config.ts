import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@cifra/api-client", "@cifra/shared-types"],
};

export default nextConfig;
