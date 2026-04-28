import { type Page } from "@playwright/test";

export const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME ?? "admin";
export const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "changeme";

export async function login(page: Page, username = ADMIN_USERNAME, password = ADMIN_PASSWORD) {
  await page.goto("/login");
  await page.getByLabel(/username/i).fill(username);
  await page.getByLabel(/password/i).fill(password);
  await page.getByRole("button", { name: /login/i }).click();
  // Wait for redirect to dashboard
  await page.waitForURL(/^\/(agents|$)/, { timeout: 10_000 });
}
