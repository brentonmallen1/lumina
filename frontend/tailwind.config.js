/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'media',
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: '#6366f1',
          hover:   '#4f46e5',
          subtle:  '#e5e5f8',
          shadow:  'rgba(99,102,241,0.3)',
        },
        surface: {
          DEFAULT: '#eef0f3',
          hover:   '#e0e3e8',
          bg:      '#e6e8ec',
        },
        'app-text':  '#1e2330',
        'app-muted': '#4d5464',
        'app-border': '#c8cdd5',
        'app-border-hover': '#b8bdc5',
        'app-border-focus': '#6366f1',
      },
      borderRadius: {
        card: '12px',
      },
      boxShadow: {
        card:       '0 1px 3px rgba(30,35,48,0.06), 0 4px 16px rgba(30,35,48,0.06)',
        'card-hover':'0 2px 8px rgba(30,35,48,0.08), 0 8px 24px rgba(30,35,48,0.08)',
        focus:      '0 0 0 3px rgba(99,102,241,0.4)',
      },
      fontFamily: {
        mono: ['"SF Mono"', '"Fira Code"', '"Fira Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
};
