/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Ficshon brand accent (emerald)
        fic: {
          accent:    'rgb(var(--fic-accent) / <alpha-value>)',
          accent600: 'rgb(var(--fic-accent-600) / <alpha-value>)',
        },
      },
    },
  },
  plugins: [],
}
