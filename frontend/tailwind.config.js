/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          900: "#0b0c10",
          800: "#1f2833",
          700: "#2a3644",
          600: "#45a29e",
        },
        accent: {
          cyan: "#66fcf1",
          blue: "#3b82f6",
          purple: "#8b5cf6",
          pink: "#ec4899",
        }
      },
      fontFamily: {
        sans: ['"Inter"', '"Prompt"', 'sans-serif'],
      }
    },
  },
  plugins: [],
}
