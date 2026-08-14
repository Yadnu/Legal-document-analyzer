import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          deep: "#0d1117",
          DEFAULT: "#161b22",
          card: "#1c2331",
          hover: "#21293a",
        },
        ink: {
          DEFAULT: "#e6e1d3",
          muted: "#8b949e",
          faint: "#4a5568",
        },
        gold: {
          DEFAULT: "#d4a843",
          bright: "#e8c05a",
          dim: "#a07830",
          glow: "rgba(212,168,67,0.15)",
        },
        status: {
          ready: "#3fb950",
          processing: "#d4a843",
          failed: "#f85149",
        },
      },
      fontFamily: {
        display: ["Fraunces", "Georgia", "serif"],
        sans: ["Outfit", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      boxShadow: {
        gold: "0 0 0 1px rgba(212,168,67,0.4), 0 4px 20px rgba(212,168,67,0.1)",
        card: "0 1px 3px rgba(0,0,0,0.4), 0 4px 16px rgba(0,0,0,0.2)",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [typography],
};

export default config;
