/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#070b16',
          900: '#0b1020',
          850: '#0f1528',
          800: '#141b31',
          700: '#1c2440',
          600: '#28314f',
          500: '#3b466b',
          400: '#5c6790',
          300: '#8b95b8',
          200: '#c0c7dd',
          100: '#e4e8f3',
          50: '#f5f7fc',
        },
        accent: {
          300: '#b7a6ff',
          400: '#9b85fd',
          500: '#7c5cfc',
          600: '#6541e8',
          700: '#5231c4',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'PingFang SC',
          'Hiragino Sans GB',
          'Microsoft YaHei',
          'sans-serif',
        ],
        mono: ['JetBrains Mono', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(4, 8, 20, 0.4), 0 8px 24px -12px rgba(4, 8, 20, 0.5)',
        glow: '0 0 0 1px rgba(124, 92, 252, 0.35), 0 8px 30px -10px rgba(124, 92, 252, 0.45)',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.55' },
        },
      },
      animation: {
        'fade-in': 'fade-in 180ms ease-out',
        'pulse-soft': 'pulse-soft 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
