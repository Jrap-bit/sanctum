import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: '/api/v1/:path*', destination: `${process.env.BACKEND_URL || 'http://127.0.0.1:8000'}/api/v1/:path*` }];
  },
  async headers() {
    return [{ source: '/:path*', headers: [
      { key: 'Cache-Control', value: 'private, no-store' },
      { key: 'Referrer-Policy', value: 'no-referrer' },
      { key: 'X-Content-Type-Options', value: 'nosniff' }
    ] }];
  }
};
export default nextConfig;
