import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#EFEFEF",
        panel: "#F8F8F8",
        ink: "#111111",
        soft: "#444444",
        faint: "#666666",
        line: "#D6D6D6",
        accent: "#FF4B22",
        "accent-deep": "#C7300E",
        "accent-tint": "#FFE9E2",
      },
      fontFamily: {
        sans: ['"Google Sans Flex"', '"Google Sans"', "system-ui", "-apple-system", '"Segoe UI"', "Roboto", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(17,17,17,.04), 0 10px 28px -14px rgba(17,17,17,.14)",
        pop: "0 24px 70px -24px rgba(17,17,17,.5)",
      },
    },
  },
  plugins: [],
};

export default config;