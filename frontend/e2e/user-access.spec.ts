import { test, expect } from "@playwright/test";
import { login } from "./helpers";

const TEST_USERNAME = `e2e-user-${Date.now()}`;
const TEST_PASSWORD = "TestPass123!";

test.describe("User lifecycle — create → access grant → reverse lookup", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test("create user, grant agent access, verify access appears on agent detail", async ({ page }) => {
    // ── 1. Create a new user ──────────────────────────────────────────────
    await page.getByRole("link", { name: /users/i }).click();
    await page.waitForURL(/\/users$/);
    await page.getByRole("link", { name: /new user/i }).click();
    await page.waitForURL(/\/users\/new/);

    await page.getByLabel(/username/i).fill(TEST_USERNAME);
    await page.getByLabel(/password/i).fill(TEST_PASSWORD);
    await page.getByRole("button", { name: /create/i }).click();

    // Should redirect to user detail
    await page.waitForURL(/\/users\/\d+/);
    await expect(page.getByText(TEST_USERNAME)).toBeVisible();

    // ── 2. Go to agents list and pick the first agent ─────────────────────
    await page.getByRole("link", { name: /agents/i }).first().click();
    await page.waitForURL(/\/agents$/);

    const firstAgentRow = page.getByRole("row").nth(1);
    const agentName = await firstAgentRow.getByRole("cell").first().innerText();

    // Navigate to the agent's detail page
    await firstAgentRow.getByRole("link").click();
    await page.waitForURL(/\/agents\/\d+/);

    // ── 3. Grant access to the new user ──────────────────────────────────
    // Click into the user-meta / access section
    const userMetaLink = page.getByRole("link", { name: new RegExp(TEST_USERNAME, "i") });
    // If user list doesn't exist yet, use the "Add User Access" button pattern
    // Navigate to user-meta edit for this agent + user principal
    const agentId = page.url().match(/\/agents\/(\d+)/)?.[1];
    await page.goto(`/agents/${agentId}/user-meta/${TEST_USERNAME}`);

    // Page should load the user-meta edit form
    await expect(page.getByText(/user meta/i)).toBeVisible({ timeout: 5_000 });

    // ── 4. Back to user detail — verify access entry exists ──────────────
    await page.getByRole("link", { name: /users/i }).click();
    await page.waitForURL(/\/users$/);
    await page.getByRole("row", { name: new RegExp(TEST_USERNAME, "i") }).getByRole("link").click();
    await page.waitForURL(/\/users\/\d+/);

    // Access tab should show the agent
    const accessTab = page.getByRole("tab", { name: /access/i });
    if (await accessTab.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await accessTab.click();
    }
    await expect(page.getByText(agentName)).toBeVisible({ timeout: 5_000 });
  });
});
