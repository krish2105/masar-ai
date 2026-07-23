/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Proxy API calls to FastAPI in development so the browser sees one origin
    // and no CORS preflight sits in front of the SSE stream.
    return [{ source: '/api/:path*', destination: 'http://127.0.0.1:8000/api/:path*' }];
  },
};
export default nextConfig;
