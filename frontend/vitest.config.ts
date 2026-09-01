import path from 'path';
import { defineConfig } from 'vitest/config';

// B15.6: Vitest configuration for pure logic unit tests.
// No DOM environment needed — session guard tests are pure TypeScript functions.
export default defineConfig({
  // Mirrors vite.config.ts. Tests used to import only from modules that happened
  // to use relative paths, so the missing alias went unnoticed until a module
  // under test imported '@/...' and failed to resolve. Kept identical to the
  // build config so a test never resolves a different file from the app.
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
});
