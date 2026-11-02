import js from '@eslint/js'
import globals from 'globals'

/**
 * Vite/esbuild bundles fine even when a component references a variable it
 * never declared — the bug only shows up at runtime, as a blank screen. That
 * is exactly how `lang` slipped into MonitorView: it was passed in the JSX
 * and used in the body, but never listed in the props.
 *
 * So the lint runs as part of the build. An undeclared variable now fails
 * `npm run build` instead of failing on the user's screen.
 */
export default [
  js.configs.recommended,
  {
    files: ['src/**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.es2021 },
    },
    rules: {
      'no-undef': 'error',
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
    },
  },
]
