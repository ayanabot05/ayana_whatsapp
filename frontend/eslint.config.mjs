import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import react from "eslint-plugin-react";

export default [
  {
    ignores: [
      "build/**",
      "node_modules/**",
      "coverage/**",
      "plugins/**",
      "public/**",
      "craco.config.js",
      "playwright.config.js",
      "postcss.config.js",
      "tailwind.config.js",
      "eslint.config.mjs",
    ],
  },
  js.configs.recommended,
  { linterOptions: { reportUnusedDisableDirectives: "off" } },
  {
    files: ["**/*.{js,jsx}"],
    plugins: { "react-hooks": reactHooks, react: react },
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      "no-unused-vars": "off",
      "no-undef": "off",
      "no-empty": "off",
      "no-useless-escape": "off",
      "no-cond-assign": "off",
      "no-control-regex": "off",
      "no-prototype-builtins": "off",
      "no-misleading-character-class": "off",
      "no-constant-condition": "off",
      "no-fallthrough": "off",
      "no-irregular-whitespace": "off",
      "no-sparse-arrays": "off",
      "no-redeclare": "off",
      "no-func-assign": "off",
      "react-hooks/exhaustive-deps": "off",
      "react-hooks/rules-of-hooks": "off",
      "react/no-unescaped-entities": "off",
      "react/jsx-no-target-blank": "off",
      "react/prop-types": "off",
    },
  },
];
