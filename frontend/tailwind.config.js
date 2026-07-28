// Built with Spec4 AI - https://spec4.ai
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  // Class strategy: the `dark` class on <html> is toggled by useTheme, so the
  // visitor's stored preference wins over the OS setting once they choose one.
  darkMode: 'class',
  theme: {
    extend: {},
  },
  plugins: [],
}
