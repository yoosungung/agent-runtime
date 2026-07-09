#!/usr/bin/env node
/**
 * Capture admin UI screenshots for docs/운영가이드.md
 *
 * Usage (from frontend/ — Playwright dep):
 *   cd frontend
 *   E2E_BASE_URL=https://agents.k8s-test E2E_ADMIN_PASSWORD='...' \
 *     node ../scripts/capture-ops-screenshots.mjs
 */
import { chromium } from "@playwright/test";
import { mkdir } from "fs/promises";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BASE = process.env.E2E_BASE_URL ?? "http://127.0.0.1:18000";
const USER = process.env.E2E_ADMIN_USERNAME ?? "admin";
const PASS = process.env.E2E_ADMIN_PASSWORD ?? "";
const OUT = join(ROOT, "assets/ops");

if (!PASS) {
  console.error("E2E_ADMIN_PASSWORD is required");
  process.exit(1);
}

await mkdir(OUT, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  ignoreHTTPSErrors: true,
});
const page = await context.newPage();

async function shot(name) {
  const path = join(OUT, `${name}.png`);
  await page.screenshot({ path, fullPage: false });
  console.log("saved", path, page.url());
}

async function login() {
  await page.goto(`${BASE}/login`);
  await page.locator('input[type="text"]').fill(USER);
  await page.locator('input[type="password"]').fill(PASS);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(2500);
  if (page.url().includes("/login")) {
    throw new Error("login failed — check E2E_ADMIN_PASSWORD");
  }
}

await page.goto(`${BASE}/login`);
await shot("01-login");
await login();
await shot("02-dashboard");

for (const [path, name] of [
  ["/agents", "03-agents-general"],
  ["/bundle/agents", "04-bundle-agents"],
  ["/bundle/mcp", "04c-bundle-mcp"],
  ["/chat", "05-chat"],
  ["/users", "06-users"],
  ["/settings/infra", "07-settings-infra"],
  ["/pipeline", "08-pipeline"],
  ["/vfs/agent", "09-vfs-agent"],
  ["/me", "10-profile"],
]) {
  await page.goto(`${BASE}${path}`);
  await page.waitForTimeout(2000);
  await shot(name);
}

await browser.close();
