const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '.',
  testMatch: 'terminal.spec.js',
  timeout: 30_000,
  retries: 0,
  workers: 1,
  use: {
    baseURL: process.env.TTYD_TEST_URL,
    httpCredentials: { username: 'synthetic', password: 'synthetic-password' },
    headless: true,
  },
});
