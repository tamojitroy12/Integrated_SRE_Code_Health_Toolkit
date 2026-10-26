import { type Browser, expect, test } from "@playwright/test";

// Visual review harness (opt-in): signs in and captures every screen in both themes at desktop and
// mobile widths into test-results/screens/. SCREENS_IDS is JSON with ids of a data-rich project:
//   {"project": "...", "target": "...", "alert": "...", "finding": "...", "scan": "..."}
const EMAIL = process.env.E2E_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_PASSWORD ?? "";
const IDS = JSON.parse(process.env.SCREENS_IDS ?? "{}") as Record<string, string>;
const ONLY = process.env.SCREENS_ONLY ? process.env.SCREENS_ONLY.split(",") : undefined;

test.skip(!process.env.SCREENSHOTS || !PASSWORD, "set SCREENSHOTS=1 and E2E_PASSWORD");
test.describe.configure({ mode: "serial" });

function pages(): [string, string][] {
  const p = `/projects/${IDS.project}`;
  return [
    ["projects", "/projects"],
    ["new-project", "/projects/new"],
    ["new-project-instrument", `/projects/new?project=${IDS.project}&step=3&target=${IDS.target}`],
    ["overview", p],
    ["monitoring", `${p}/monitoring`],
    ["alerts", `${p}/alerts?status=all`],
    ["alert-detail", `${p}/alerts/${IDS.alert}`],
    ["alert-rules", `${p}/alerts/rules`],
    ["findings", `${p}/code-health`],
    ["finding-detail", `${p}/code-health/findings/${IDS.finding}`],
    ["scans", `${p}/code-health/scans`],
    ["scan-detail", `${p}/code-health/scans/${IDS.scan}`],
    ["fix-proposals", `${p}/code-health/fix-proposals`],
    ["settings", `${p}/settings`],
    ["admin-users", "/admin"],
    ["admin-channels", "/admin/channels"],
    ["admin-audit", "/admin/audit"],
  ].filter(([name]) => !ONLY || ONLY.includes(name)) as [string, string][];
}

async function capture(browser: Browser, theme: "dark" | "light", device: "desktop" | "mobile") {
  const context = await browser.newContext({
    colorScheme: theme,
    viewport: device === "desktop" ? { width: 1440, height: 900 } : { width: 390, height: 844 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByLabel("Email").waitFor();
  if (!ONLY || ONLY.includes("login")) await page.screenshot({ path: `test-results/screens/login-${theme}-${device}.png` });
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/projects/);
  for (const [name, url] of pages()) {
    await page.goto(url);
    await page.locator("main h1").first().waitFor({ timeout: 30_000 }).catch(() => undefined);
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `test-results/screens/${name}-${theme}-${device}.png`, fullPage: true });
  }
  if (device === "desktop" && (!ONLY || ONLY.includes("overlays"))) {
    // Overlays: command palette, a type-to-confirm dialog (dismissed, nothing is archived), and the mobile drawer.
    await page.goto(`/projects/${IDS.project}`);
    await page.locator("main h1").first().waitFor();
    await page.keyboard.press("Control+k");
    await page.keyboard.type("hand");
    await page.waitForTimeout(1200);
    await page.screenshot({ path: `test-results/screens/palette-${theme}-${device}.png` });
    await page.keyboard.press("Escape");
    await page.goto(`/projects/${IDS.project}/settings`);
    await page.getByRole("button", { name: "Archive project" }).click();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `test-results/screens/confirm-${theme}-${device}.png` });
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  }
  if (device === "mobile" && (!ONLY || ONLY.includes("overlays"))) {
    await page.goto(`/projects/${IDS.project}`);
    await page.getByRole("button", { name: "Menu", exact: true }).click();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `test-results/screens/drawer-${theme}-${device}.png` });
  }
  await context.close();
}

for (const theme of ["dark", "light"] as const) {
  for (const device of ["desktop", "mobile"] as const) {
    test(`screens ${theme} ${device}`, async ({ browser }, info) => {
      test.skip(info.project.name !== "chromium", "captured once, from the desktop project");
      test.setTimeout(240_000);
      await capture(browser, theme, device);
    });
  }
}
