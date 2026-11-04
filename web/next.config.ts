import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // stop the dev server from writing its own instruction files into the project
  agentRules: false,
  // the pages are opened as localhost or 127.0.0.1; let both load the dev server's resources
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
