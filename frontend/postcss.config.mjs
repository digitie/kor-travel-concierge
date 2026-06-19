/** @type {import('postcss-load-config').Config} */
const config = {
  plugins: {
    // Tailwind CSS v4 — vendor prefixing은 이 플러그인이 내장 처리한다(autoprefixer 불필요).
    "@tailwindcss/postcss": {},
  },
};

export default config;
