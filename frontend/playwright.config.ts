import {defineConfig,devices} from '@playwright/test';
export default defineConfig({
  testDir:'./e2e',fullyParallel:false,reporter:'list',timeout:45_000,
  use:{baseURL:process.env.E2E_BASE_URL||'http://127.0.0.1:3000',trace:'retain-on-failure',screenshot:'only-on-failure',
    launchOptions:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{}},
  // The suite covers the real lifecycle once; the viewport test resizes that same browser.
  projects:[{name:'desktop-chromium',use:{...devices['Desktop Chrome']}}],
  outputDir:'test-results'
});
