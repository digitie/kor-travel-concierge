import { defineConfig, globalIgnores } from "eslint/config";
import next from "@next/eslint-plugin-next";
import { createTypeScriptImportResolver } from "eslint-import-resolver-typescript";
import importX from "eslint-plugin-import-x";
import a11y from "eslint-plugin-jsx-a11y-x";
import hooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

// ESLint 10의 flat config와 API를 지원하는 plugin으로 기존 Next/TS/hooks 검사를 구성한다.
export default defineConfig([
  ...tseslint.configs.recommended,
  importX.flatConfigs.recommended,
  {
    settings: {
      "import-x/resolver-next": [createTypeScriptImportResolver({ project: "./tsconfig.json" })],
    },
    rules: {
      "@typescript-eslint/no-unused-vars": "warn",
      "import-x/no-anonymous-default-export": "warn",
    },
  },
  hooks.configs.flat["recommended-latest"],
  next.configs.recommended,
  next.configs["core-web-vitals"],
  {
    plugins: { "jsx-a11y-x": a11y },
    rules: {
      "jsx-a11y-x/alt-text": ["warn", { elements: ["img"], img: ["Image"] }],
      "jsx-a11y-x/aria-props": "warn",
      "jsx-a11y-x/aria-proptypes": "warn",
      "jsx-a11y-x/aria-unsupported-elements": "warn",
      "jsx-a11y-x/role-has-required-aria-props": "warn",
      "jsx-a11y-x/role-supports-aria-props": "warn",
    },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts", "playwright-report/**", "test-results/**"]),
]);
