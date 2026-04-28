import { test, expect } from "@playwright/test";
import { login } from "./helpers";

const AGENT_NAME = `e2e-agent-${Date.now()}`;
const AGENT_VERSION = "0.0.1";

test.describe("Agent lifecycle — register → detail → retire", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test("create agent via URI tab, view detail, retire", async ({ page }) => {
    // Navigate to agents list
    await page.getByRole("link", { name: /agents/i }).first().click();
    await page.waitForURL(/\/agents$/);

    // Click New Agent
    await page.getByRole("link", { name: /new agent/i }).click();
    await page.waitForURL(/\/agents\/new/);

    // Fill URI tab form
    await page.getByPlaceholder("my-agent").fill(AGENT_NAME);
    await page.getByPlaceholder("1.0.0").fill(AGENT_VERSION);

    // Select runtime pool
    await page.selectOption("select", { index: 1 });

    // Entrypoint
    await page.getByPlaceholder("module.path:factory").fill("my_agent.main:factory");

    // Submit
    await page.getByRole("button", { name: /create/i }).click();

    // Should navigate to detail page
    await page.waitForURL(/\/agents\/\d+/);
    await expect(page.getByText(AGENT_NAME)).toBeVisible();
    await expect(page.getByText(AGENT_VERSION)).toBeVisible();

    // Retire the agent
    await page.getByRole("button", { name: /retire/i }).click();

    // Confirm retire (if confirmation dialog appears)
    const confirmBtn = page.getByRole("button", { name: /confirm|yes|ok/i });
    if (await confirmBtn.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await confirmBtn.click();
    }

    // Retired badge should appear
    await expect(page.getByText(/retired/i)).toBeVisible({ timeout: 5_000 });
  });
});
