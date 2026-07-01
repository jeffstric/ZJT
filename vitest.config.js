import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['web/**/*.test.js'],
    globals: true,
    setupFiles: ['web/tests/setup.js'],
  },
});
