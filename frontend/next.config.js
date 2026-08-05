/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Increase proxy timeout for rewrite calls that take > 30 seconds
  // (e.g. Sync All makes ~21 Amazon API calls and takes up to 90 seconds)
  experimental: {
    proxyTimeout: 120000, // 2 minutes
  },
  async rewrites() {
    // API_URL is the server-to-server URL used by the Next.js proxy.
    // In Docker: http://api:8000 (Docker network hostname)
    // In local dev (outside Docker): http://localhost:8000
    const apiUrl = process.env.API_URL || 'http://localhost:8000';
    return [
      {
        source: '/backend/:path*',
        destination: `${apiUrl}/:path*`,
      },
    ];
  },
  webpack: (config, { dev }) => {
    if (dev) {
      config.watchOptions = {
        poll: 1000,
        aggregateTimeout: 300,
      };
    }
    return config;
  },
};

module.exports = nextConfig;
