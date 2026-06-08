import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

function cssVariableColor(name: string): string {
  const resolveColor = ({ opacityValue }: { opacityValue?: string }) => {
    if (opacityValue === undefined) {
      return `var(${name})`;
    }
    return `color-mix(in oklab, var(${name}) calc(${opacityValue} * 100%), transparent)`;
  };
  return resolveColor as unknown as string;
}

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      borderRadius: {
        "4xl": "2rem",
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      colors: {
        background: cssVariableColor("--background"),
        foreground: cssVariableColor("--foreground"),
        card: {
          DEFAULT: cssVariableColor("--card"),
          foreground: cssVariableColor("--card-foreground"),
        },
        popover: {
          DEFAULT: cssVariableColor("--popover"),
          foreground: cssVariableColor("--popover-foreground"),
        },
        primary: {
          DEFAULT: cssVariableColor("--primary"),
          foreground: cssVariableColor("--primary-foreground"),
        },
        secondary: {
          DEFAULT: cssVariableColor("--secondary"),
          foreground: cssVariableColor("--secondary-foreground"),
        },
        muted: {
          DEFAULT: cssVariableColor("--muted"),
          foreground: cssVariableColor("--muted-foreground"),
        },
        accent: {
          DEFAULT: cssVariableColor("--accent"),
          foreground: cssVariableColor("--accent-foreground"),
        },
        destructive: {
          DEFAULT: cssVariableColor("--destructive"),
          foreground: cssVariableColor("--destructive-foreground"),
        },
        border: cssVariableColor("--border"),
        input: cssVariableColor("--input"),
        ring: cssVariableColor("--ring"),
        sidebar: {
          DEFAULT: cssVariableColor("--sidebar"),
          foreground: cssVariableColor("--sidebar-foreground"),
          primary: cssVariableColor("--sidebar-primary"),
          "primary-foreground": cssVariableColor("--sidebar-primary-foreground"),
          accent: cssVariableColor("--sidebar-accent"),
          "accent-foreground": cssVariableColor("--sidebar-accent-foreground"),
          border: cssVariableColor("--sidebar-border"),
          ring: cssVariableColor("--sidebar-ring"),
        },
      },
    },
  },
  plugins: [tailwindcssAnimate],
};

export default config;
