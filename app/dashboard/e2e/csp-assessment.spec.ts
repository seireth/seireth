import { test, expect } from "@playwright/test";
import { pathToFileURL } from "node:url";

for (const combined of [false, true]) {
  test(`CSP assessment and offline report with ${combined ? "combined" : "standalone"} selection`, async ({ page, browser }) => {
    const projectName = `CSP browser test ${combined} ${Date.now()}`;
    await page.goto("/dashboard/");
    await page.getByLabel("Project name").fill(projectName);
    await page.getByRole("button", { name: "Create project", exact: true }).click();
    await page.locator(".project-card").filter({ hasText: projectName }).click();
    await page.getByRole("link", { name: "New assessment" }).click();
    await page.getByRole("button", { name: "Register a new target" }).click();
    await page.getByLabel("Target name").fill("CSP permissions");
    await page.getByLabel("Registered URL").fill("http://demo-app:8080/");
    await page.getByLabel("Docker image").fill("seireth/demo-app:local");
    await page.getByRole("button", { name: "Register target", exact: true }).click();
    await expect(page.getByLabel("Assessment URL")).toHaveValue("http://demo-app:8080/");
    await page.getByLabel("Assessment URL").fill("http://demo-app:8080/csp/permissive");
    await page.getByRole("checkbox", { name: /HTTP security headers/ }).setChecked(combined);
    await page.getByRole("checkbox", { name: /HTTP cookie security/ }).uncheck();
    await page.getByRole("checkbox", { name: /CSP policy/ }).check();
    await page.getByRole("button", { name: "Run assessment", exact: true }).click();
    await expect(page.getByText("completed", { exact: true }).first()).toBeVisible({ timeout: 60_000 });
    await expect(page.locator(".finding")).toHaveCount(3);
    await expect(page.getByText("Verified", { exact: true })).toBeVisible();
    for (const details of await page.locator(".finding details").all()) {
      await details.locator("summary").click();
    }
    await expect(page.locator(".evidence").getByText("Effective unsafe-eval permission")).toBeVisible();
    await expect(page.getByText("Any HTTPS origin")).toBeVisible();

    const id = page.url().split("/").at(-1)!;
    const reportResponse = await page.request.get(`/api/v1/assessments/${id}/report`);
    expect(reportResponse.ok()).toBe(true);
    const report = await reportResponse.json();
    expect(report.schema_version).toBe(1);
    expect(report.assessment.plugins).toEqual(combined ? ["http-security-headers", "csp-policy"] : ["csp-policy"]);
    expect(report.assessment.result.sandbox_backend).toBe("docker");
    expect(report.assessment.result.cleanup_verified).toBe(true);
    const csp = report.assessment.result.routes[0].plugins.find((item: {id: string}) => item.id === "csp-policy");
    expect(csp.checks.map((item: {status: string}) => item.status)).toEqual(["failed", "failed", "failed"]);
    if (combined) {
      const baseline = report.assessment.result.routes[0].plugins.find((item: {id: string}) => item.id === "http-security-headers");
      expect(baseline.checks.map((item: {status: string}) => item.status)).toEqual(["passed", "passed", "passed"]);
    }

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download HTML", exact: true }).click();
    const download = await downloadPromise;
    const path = test.info().outputPath("csp-report.html");
    await download.saveAs(path);
    const offlineContext = await browser.newContext({ offline: true });
    try {
      const offline = await offlineContext.newPage();
      await offline.goto(pathToFileURL(path).href);
      await expect(offline.locator(".finding")).toHaveCount(3);
      await expect(offline.locator(".evidence").getByText("Effective unsafe-eval permission")).toBeVisible();
      await expect(offline.locator(".evidence li")).toHaveCount(4);
      expect(await offline.locator("script, img, link, [src]").count()).toBe(0);
      for (const width of [1280, 390]) {
        await offline.setViewportSize({ width, height: 844 });
        expect(await offline.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      }
      await offline.screenshot({ path: test.info().outputPath("csp-report-mobile.png"), fullPage: true });
    } finally {
      await offlineContext.close();
    }
  });
}
