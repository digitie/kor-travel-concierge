import type { Config } from "tailwindcss";

// Tailwind CSS v4. globals.css의 `@config`로 로드된다. v4는 `var(--x)` 색상 값에
// opacity modifier(`bg-primary/80` 등)를 color-mix로 자동 처리하므로 별도 helper가 필요 없다.
// animation 유틸리티는 globals.css의 `@import "tw-animate-css"`가 제공한다.
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
        background: "var(--background)",
        foreground: "var(--foreground)",
        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },
        border: "var(--border)",
        input: "var(--input)",
        ring: "var(--ring)",
        sidebar: {
          DEFAULT: "var(--sidebar)",
          foreground: "var(--sidebar-foreground)",
          primary: "var(--sidebar-primary)",
          "primary-foreground": "var(--sidebar-primary-foreground)",
          accent: "var(--sidebar-accent)",
          "accent-foreground": "var(--sidebar-accent-foreground)",
          border: "var(--sidebar-border)",
          ring: "var(--sidebar-ring)",
        },
        // --- StyleSeed/geo semantic 토큰 (docs/DESIGN-RULES.md). 새 UI는 이 토큰을 먼저 쓴다. ---
        text: {
          strong: "var(--text-strong)",
          primary: "var(--text-primary)",
          secondary: "var(--text-secondary)",
          tertiary: "var(--text-tertiary)",
          disabled: "var(--text-disabled)",
        },
        surface: {
          page: "var(--surface-page)",
          card: "var(--surface-card)",
          subtle: "var(--surface-subtle)",
          muted: "var(--surface-muted)",
          row: "var(--surface-row)",
        },
        ink: "var(--text-strong)",
        line: "var(--line)",
        brand: {
          DEFAULT: "var(--brand)",
          foreground: "var(--brand-foreground)",
          ink: "var(--brand-ink)",
          tint: "var(--brand-tint)",
        },
        info: "var(--info)",
        success: "var(--success)",
        warning: "var(--warning)",
        warn: "var(--warning)",
        danger: "var(--danger)",
        icon: {
          default: "var(--icon-default)",
        },
      },
      boxShadow: {
        card: "var(--shadow-card)",
        "card-hover": "var(--shadow-card-hover)",
        elevated: "var(--shadow-elevated)",
        button: "var(--shadow-button)",
        modal: "var(--shadow-modal)",
      },
      transitionTimingFunction: {
        default: "var(--ease-default)",
      },
      transitionDuration: {
        fast: "var(--duration-fast)",
        normal: "var(--duration-normal)",
      },
    },
  },
  plugins: [],
};

export default config;
