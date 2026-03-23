/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // 主色调 — 由 CSS 变量 --color-primary-rgb 驱动，支持运行时切换
        primary: {
          DEFAULT: 'rgb(var(--color-primary-rgb) / <alpha-value>)',
          50: '#F0EFFF',
          100: '#E0DEFF',
          200: '#C1BDFF',
          300: '#A29CFF',
          400: '#837BFF',
          500: '#6C63FF',
          600: 'rgb(var(--color-primary-dark-rgb) / <alpha-value>)',
          700: '#2819FF',
          800: '#0D00F0',
          900: '#0A00BD',
        },
        // Light mode
        surface: {
          DEFAULT: '#FAFAFA',
          sidebar: '#F5F5F5',
          card: '#FFFFFF',
          divider: '#E5E5EA',
        },
        // Dark mode
        dark: {
          DEFAULT: '#1A1A2E',
          sidebar: '#16213E',
          card: '#0F3460',
          divider: '#2A2A4A',
        },
        // 文字颜色
        text: {
          primary: '#2D2D2D',
          secondary: '#8E8E93',
          'dark-primary': '#E8E8E8',
          'dark-secondary': '#A0A0A0',
        },
      },
      borderRadius: {
        card: '12px',
        button: '8px',
        input: '10px',
      },
      boxShadow: {
        light: '0 2px 8px rgba(0,0,0,0.06)',
        float: '0 8px 32px rgba(0,0,0,0.12)',
      },
      transitionDuration: {
        DEFAULT: '200ms',
      },
      transitionTimingFunction: {
        DEFAULT: 'ease-out',
      },
      spacing: {
        // 基于 4px 网格系统
        '4.5': '18px',
      },
    },
  },
  plugins: [],
};

