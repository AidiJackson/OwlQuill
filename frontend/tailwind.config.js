/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        // Self-hosted (public/fonts, declared in src/fonts.css)
        sans:  ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        serif: ['"Playfair Display"', 'Georgia', 'serif'],
        mono:  ['"DM Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        // Ficshon brand tokens (legacy — unmigrated pages)
        fic: {
          accent:    'rgb(var(--fic-accent) / <alpha-value>)',
          accent600: 'rgb(var(--fic-accent-600) / <alpha-value>)',
          purple:    'rgb(var(--fic-purple) / <alpha-value>)',
          purple600: 'rgb(var(--fic-purple-600) / <alpha-value>)',
        },
        // UI v2 semantic tokens — follow the active gem + light/dark mode.
        // Usage: bg-app, bg-surface, bg-surface-elevated, text-ink, text-ink-2,
        //        border-edge, border-edge-md, text-gem, bg-gem-soft, …
        gem: {
          DEFAULT: 'rgb(var(--gem) / <alpha-value>)',
          soft:    'var(--accent-soft)',
          border:  'var(--accent-border)',
          glow:    'var(--accent-glow)',
          ink:     'var(--gem-ink)',
        },
        app: 'var(--bg)',
        surface: {
          DEFAULT:  'var(--surface)',
          elevated: 'var(--elevated)',
          overlay:  'var(--overlay)',
        },
        ink: {
          DEFAULT: 'var(--text)',
          2:       'var(--text-2)',
          3:       'var(--text-3)',
        },
        edge: {
          DEFAULT: 'var(--border)',
          md:      'var(--border-md)',
        },
      },
    },
  },
  plugins: [],
}
