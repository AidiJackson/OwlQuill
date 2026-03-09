import { defineConfig } from 'vitest/config';

// B15.6: Vitest configuration for pure logic unit tests.
// No DOM environment needed — session guard tests are pure TypeScript functions.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
});
