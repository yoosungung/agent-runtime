import { test, expect } from "@playwright/test";
import { login } from "./helpers";

const TEST_USERNAME = `e2e-user-${Date.now()}`;
const TEST_PASSWORD = "TestPass123!";

test.describe("User lifecycle — create → access grant → self-service", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test("create user, grant agent access, user configures via /me/integrations", async ({
    page,
  }) => {
    // ── 1. Create a new user ──────────────────────────────────────────────
    await page.getByRole("link", { name: "User" }).click();
    await page.waitForURL(/\/users$/);
    await page.getByRole("link", { name: /new user/i }).click();
    await page.waitForURL(/\/users\/new/);

    await page.getByLabel(/username/i).fill(TEST_USERNAME);
    await page.getByLabel(/password/i).fill(TEST_PASSWORD);
    await page.getByRole("button", { name: /create/i }).click();

    await page.waitForURL(/\/users\/\d+/);
    await expect(page.getByText(TEST_USERNAME)).toBeVisible();

    // ── 2. Pick first bundle agent and grant access ───────────────────────
    await page.getByRole("link", { name: "Bundle" }).click();
    await page.waitForURL(/\/bundle\/agents$/);

    const firstAgentRow = page.getByRole("row").nth(1);
    const agentName = (await firstAgentRow.getByRole("cell").first().innerText()).trim();

    await firstAgentRow.getByRole("link").click();
    await page.waitForURL(/\/agents\/\d+/);

    await page.getByRole("button", { name: /access/i }).click();
    await page.getByPlaceholder(/add user by username/i).fill(TEST_USERNAME);
    await page.getByRole("button", { name: TEST_USERNAME, exact: true }).click();
    await expect(page.getByText(TEST_USERNAME)).toBeVisible({ timeout: 5_000 });

    // ── 3. Login as the new user and open integrations ────────────────────
    await page.getByRole("button", { name: /logout/i }).click();
    await page.waitForURL(/\/login/);
    await login(page, TEST_USERNAME, TEST_PASSWORD);

    await page.goto("/me");
    await expect(page.getByRole("heading", { name: /my profile/i })).toBeVisible({
      timeout: 5_000,
    });
    await page.getByRole("button", { name: /^agent$/i }).click();
    await expect(page.getByRole("link", { name: agentName })).toBeVisible({ timeout: 5_000 });

    // ── 4. Admin view: user detail access tab lists the agent ─────────────
    await page.getByRole("button", { name: /logout/i }).click();
    await login(page);

    await page.getByRole("link", { name: "User" }).click();
    await page.waitForURL(/\/users$/);
    await page.getByRole("row", { name: new RegExp(TEST_USERNAME, "i") }).getByRole("link").click();
    await page.waitForURL(/\/users\/\d+/);

    const accessTab = page.getByRole("tab", { name: /access/i });
    if (await accessTab.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await accessTab.click();
    }
    await expect(page.getByText(agentName)).toBeVisible({ timeout: 5_000 });
  });
});
