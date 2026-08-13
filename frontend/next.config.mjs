/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack: (config) => {
    // react-pdf tries to require 'canvas' on the server — suppress the error.
    config.resolve.alias.canvas = false;
    return config;
  },
};

export default nextConfig;
