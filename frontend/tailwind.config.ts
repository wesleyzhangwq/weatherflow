import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: { 50: "#f5f5f4", 100: "#eceae6", 800: "#262422", 900: "#1a1816" },
        sky: { 100: "#eef4f7", 300: "#9bbac9", 500: "#6f97ab" }
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "-apple-system",
          "Inter",
          "Segoe UI",
          "Helvetica",
          "Arial",
          "sans-serif"
        ],
        serif: ["ui-serif", "Georgia", "serif"]
      },
      borderRadius: { "2xl": "1.25rem" }
    }
  },
  plugins: []
} satisfies Config;
