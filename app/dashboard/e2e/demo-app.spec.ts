import { test, expect } from "@playwright/test";

test("the demo workspace loads its API and creates a support ticket", async ({ page }) => {
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await page.goto(process.env.SEIRETH_DEMO_APP_URL ?? "http://127.0.0.1:8081/");
  await expect(page.getByText("Live queue connected", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Manage tickets" }).click();
  const title = `Browser demo ticket ${Date.now()}`;
  await page.getByLabel("Ticket title").fill(title);
  await page.getByRole("button", { name: "Create ticket", exact: true }).click();
  await expect(page.getByRole("cell", { name: title, exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Plugin lab", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Plugin lab" })).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(38);
  expect(failures).toEqual([]);
  await page.screenshot({ path: "test-results/demo-app-lab.png", fullPage: true });
});

for (const scenario of [
  { path: "/", name: "Protected workspace", findings: 0 },
  { path: "/lab/csp-wildcard", name: "Permissive framing policy", findings: 1 },
  { path: "/cookies/protected", name: "Protected cookies", findings: 0 },
]) {
  test(`selects the new demo image and assesses ${scenario.name}`, async ({ page, request }) => {
    await page.goto("/dashboard/");
    const projectName = `Header application browser test ${scenario.name} ${Date.now()}`;
    await page.getByLabel("Project name").fill(projectName);
    await page.getByRole("button", { name: "Create project", exact: true }).click();
    await page.locator(".project-card").filter({ hasText: projectName }).click();
    const projectUrl = page.url();
    await page.getByRole("link", { name: "New assessment" }).click();
    await page.getByRole("button", { name: "Register a new target" }).click();
    await page.getByLabel("Target name").fill(scenario.name);
    await page.getByLabel("Registered URL").fill("http://demo-app:8080/");
    await page.getByLabel("Docker image").fill("seireth/demo-app:local");
    await page.getByRole("button", { name: "Register target", exact: true }).click();
    await expect(page.getByLabel("Assessment URL")).toHaveValue("http://demo-app:8080/");
    await page.getByLabel("Assessment URL").fill(`http://demo-app:8080${scenario.path}`);
    await page.getByRole("checkbox", { name: /HTTP security headers/ }).check();
    if (scenario.path.startsWith("/cookies"))
      await page.getByRole("checkbox", { name: /HTTP cookie security/ }).check();
    await page.getByRole("button", { name: "Run assessment", exact: true }).click();
    await expect(page.getByText("completed", { exact: true }).first()).toBeVisible({ timeout: 60_000 });
    await expect(page.locator(".finding")).toHaveCount(scenario.findings);
    await expect(page.getByText("Verified", { exact: true })).toBeVisible();
    if (scenario.findings) {
      await expect(page.getByText("Missing or ineffective framing protection", { exact: true })).toBeVisible();
      await page.locator(".finding summary").click();
      await expect(page.getByRole("region", { name: "Finding evidence" })).toBeVisible();
    } else {
      await expect(page.getByText("No covered violations were identified.", { exact: false })).toBeVisible();
    }
    const id = page.url().split("/").at(-1)!;
    const results = await (await request.get(`/api/v1/assessments/${id}/results`)).json();
    const evidence = await (await request.get(`/api/v1/assessments/${id}/evidence`)).json();
    expect(results.result.sandbox_backend).toBe("docker");
    expect(results.result.cleanup_verified).toBe(true);
    expect(results.cleanup_pending).toBe(false);
    expect(evidence.evidence.map((entry: { data: { header: string } }) => entry.data.header)).toEqual(scenario.findings ? ["x-frame-options"] : []);
    await page.reload();
    await expect(page.locator(".finding")).toHaveCount(scenario.findings);
    await page.screenshot({ path: `test-results/demo-app-${scenario.findings}-findings.png`, fullPage: true });
    const requestSummary = page.locator(".panel").filter({has: page.getByRole("heading", {name: "Assessment request"})});
    await expect(requestSummary.getByText(`http://demo-app:8080${scenario.path}`, {exact: true}).last()).toBeVisible();
    await page.goto(projectUrl);
    await expect(page.getByRole("columnheader", {name: "Assessment URL"})).toBeVisible();
    await expect(page.getByRole("cell", {name: `http://demo-app:8080${scenario.path}`, exact: true})).toBeVisible();
  });
}
