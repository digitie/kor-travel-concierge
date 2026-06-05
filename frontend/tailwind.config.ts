import type { Config } from "tailwindcss";

// shadcn/ui 도입(T-012) 시 theme.extend와 plugins를 확장한다.
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
};

export default config;
