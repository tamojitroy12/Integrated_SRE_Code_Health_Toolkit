import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const EMAIL = process.env.E2E_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_PASSWORD ?? "";

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/projects/);
}

async function audit(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const details = results.violations.flatMap((v) =>
    v.nodes.map((n) => `${v.id}: ${n.target.join(" ")} — ${n.failureSummary?.split("\n").slice(1).join(" ").trim()}`),
  );
  expect(details).toEqual([]);
}

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test.skip(!PASSWORD, "set E2E_PASSWORD (and E2E_EMAIL) to run against a live stack");

test("login page is accessible and rejects bad credentials", async ({ page }) => {
  await page.goto("/login");
  await audit(page);
  await page.getByLabel("Email").fill("nobody@example.com");
  await page.getByLabel("Password", { exact: true }).fill("wrong-password-123");
  await page.getByRole("button", { name: "Sign in" }).click();
  // Next.js also renders a route announcer with role="alert"; match the form's message by text.
  await expect(page.getByRole("alert").filter({ hasText: /Invalid email or password|Too many/ })).toBeVisible();
});

test("create a project and see empty states on the overview", async ({ page }) => {
  await signIn(page);
  await audit(page);
  await noHorizontalOverflow(page);
  await page.getByRole("link", { name: "New project" }).click();
  // Projects run in parallel; Date.now() alone can collide (409 CONFLICT on the unique name).
  const name = `e2e-${test.info().project.name}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("button", { name: "Skip for now" }).click();
  await page.getByRole("button", { name: "Skip for now" }).click();
  await page.getByRole("link", { name: "Open project overview" }).click();
  // Generous timeout: both browser projects run in parallel against one laptop-hosted stack.
  await expect(page.getByRole("heading", { name })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("No monitoring target yet.")).toBeVisible();
  await expect(page.getByText("No repository connected.")).toBeVisible();
  await audit(page);
  await noHorizontalOverflow(page);
  for (const tab of ["Monitoring", "Alerts", "Code health", "Settings"]) {
    const nav = page.getByRole("navigation", { name: "Project" });
    if (await nav.isVisible()) {
      await nav.getByRole("link", { name: tab }).click();
    } else {
      // Narrow viewports collapse project tabs into the top-bar menu.
      await page.getByRole("button", { name: "Menu", exact: true }).click();
      await page.getByRole("banner").getByRole("link", { name: tab, exact: true }).click();
    }
    await expect(page).toHaveURL(new RegExp(`/${tab.toLowerCase().replace(" ", "-")}$`));
    await expect(page.locator("main h1").first()).toBeVisible();
    await noHorizontalOverflow(page);
  }
  // Clean up through the UI: archiving asks for the project name before it enables the button.
  await page.getByRole("button", { name: "Archive project" }).click();
  const dialog = page.getByRole("dialog");
  const confirm = dialog.getByRole("button", { name: "Archive project" });
  await expect(confirm).toBeDisabled();
  await dialog.getByRole("textbox").fill(name);
  await confirm.click();
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole("status").filter({ hasText: "Project archived" })).toBeVisible();
  await expect(page.getByRole("link", { name, exact: true })).toHaveCount(0);
});

test("command palette opens with the keyboard", async ({ page, isMobile }) => {
  test.skip(isMobile, "keyboard shortcut is a desktop affordance");
  await signIn(page);
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("combobox")).toBeFocused();
  await page.keyboard.type("All projects");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/projects$/);
});
