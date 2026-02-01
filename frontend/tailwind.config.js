/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        owl: {
          50: '#f5f3ff',
          100: '#ede9fe',
          200: '#ddd6fe',
          300: '#c4b5fd',
          400: '#a78bfa',
          500: '#8b5cf6',
          600: '#7c3aed',
          700: '#6d28d9',
          800: '#5b21b6',
          900: '#4c1d95',
          950: '#2e1065',
        },
        quill: {
          50: '#e8f5f5',
          100: '#d1ebeb',
          200: '#a3d7d7',
          300: '#75c3c3',
          400: '#3a9b9c',
          500: '#2d7d7e',
          600: '#1a5f5f',
          700: '#0f3d3e',
          800: '#0a2d2e',
          900: '#051e1f',
          950: '#031010',
        },
      },
    },
  },
  plugins: [],
}
