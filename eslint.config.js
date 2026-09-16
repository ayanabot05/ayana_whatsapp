const globals = require('./frontend/node_modules/globals');
module.exports = [
  { ignores: ['**/node_modules/**', '**/build/**', '**/public/**', '**/.local-postgres/**'] },
  {
    files: ['frontend/src/**/*.{js,jsx}'],
    languageOptions: { ecmaVersion: 'latest', sourceType: 'module', parserOptions: { ecmaFeatures: { jsx: true } }, globals: { ...globals.browser, ...globals.jest, process: 'readonly', module: 'readonly', require: 'readonly' } },
    rules: { 'no-undef': 'error', 'no-dupe-args': 'error', 'no-dupe-keys': 'error', 'valid-typeof': 'error' },
  },
];