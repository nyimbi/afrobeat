import type { Config } from "tailwindcss";
import containerQueries from "@tailwindcss/container-queries";
import animate from "tailwindcss-animate";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        // Brand palette — Afrobeats cultural identity
        "afro-gold": {
          DEFAULT: "#D4AF37",
          50: "#FAF5E0",
          100: "#F5EBC1",
          200: "#EBD783",
          300: "#E0C345",
          400: "#D4AF37",
          500: "#B8962E",
          600: "#9C7D25",
          700: "#80641C",
          800: "#644B13",
          900: "#48320A",
        },
        "afro-green": {
          DEFAULT: "#228B22",
          50: "#E8F5E8",
          100: "#C8E8C8",
          200: "#91D291",
          300: "#5ABC5A",
          400: "#33A433",
          500: "#228B22",
          600: "#1B721B",
          700: "#145914",
          800: "#0D400D",
          900: "#062706",
        },
        "afro-red": {
          DEFAULT: "#B22222",
          50: "#FAEAEA",
          100: "#F2C4C4",
          200: "#E58989",
          300: "#D74E4E",
          400: "#C43535",
          500: "#B22222",
          600: "#961B1B",
          700: "#7A1414",
          800: "#5E0D0D",
          900: "#420606",
        },
        "gbedu-purple": {
          DEFAULT: "#6B21A8",
          50: "#F3E8FF",
          100: "#E4CCFF",
          200: "#CA99FF",
          300: "#AF66FF",
          400: "#9433FF",
          500: "#7C00F0",
          600: "#6B21A8",
          700: "#581A8A",
          800: "#45136C",
          900: "#320C4E",
        },
        // Dark UI backgrounds
        "dark-bg": {
          primary: "#0A0A0F",
          secondary: "#12121A",
          tertiary: "#1A1A26",
          card: "#1E1E2E",
          elevated: "#252535",
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Inter", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "JetBrains Mono", "monospace"],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "pulse-gold": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(212, 175, 55, 0.4)" },
          "50%": { boxShadow: "0 0 0 8px rgba(212, 175, 55, 0)" },
        },
        "waveform": {
          "0%, 100%": { transform: "scaleY(0.4)" },
          "50%": { transform: "scaleY(1)" },
        },
        "slide-up": {
          from: { transform: "translateY(8px)", opacity: "0" },
          to: { transform: "translateY(0)", opacity: "1" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "shimmer": {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "pulse-gold": "pulse-gold 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "waveform": "waveform 1.2s ease-in-out infinite",
        "slide-up": "slide-up 0.3s ease-out",
        "fade-in": "fade-in 0.2s ease-out",
        "shimmer": "shimmer 2s linear infinite",
      },
      backgroundImage: {
        "gradient-afro":
          "linear-gradient(135deg, #D4AF37 0%, #6B21A8 50%, #228B22 100%)",
        "gradient-dark":
          "linear-gradient(180deg, #0A0A0F 0%, #12121A 100%)",
        "shimmer-base":
          "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.04) 50%, transparent 100%)",
      },
      boxShadow: {
        "gold": "0 0 20px rgba(212, 175, 55, 0.3)",
        "purple": "0 0 20px rgba(107, 33, 168, 0.3)",
        "glow": "0 0 40px rgba(212, 175, 55, 0.15)",
      },
    },
  },
  plugins: [animate, containerQueries],
};

export default config;
