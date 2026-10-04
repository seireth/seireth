import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { isAbsolute } from "node:path";

const dockerExecutable =
  process.env.SEIRETH_DOCKER_EXECUTABLE ??
  (process.platform === "win32"
    ? "C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe"
    : "/usr/bin/docker");
if (!isAbsolute(dockerExecutable)) {
  throw new Error("SEIRETH_DOCKER_EXECUTABLE must be an absolute executable path");
}

test("creates, refreshes, and retrieves a real cookie assessment with verified cleanup", async ({
  page,
  request,
}) => {
  await page.goto("/app/");
  const projectName = `Browser verification ${Date.now()}`;
  await page.getByLabel("Project name").fill(projectName);
  await page.getByLabel("Project name").press("Tab");
  await expect(
    page.getByRole("button", { name: "Create project", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await page.locator(".project-card").filter({ hasText: projectName }).click();
  await page.getByRole("link", { name: "New assessment" }).click();
  await page.getByRole("button", { name: "Register a new target" }).click();
  await page.getByLabel("Target name").fill("Owned cookie demo");
  await page
    .getByLabel("Registered URL")
    .fill("http://demo-target:8080/cookies");
  await page
    .getByRole("button", { name: "Register target", exact: true })
    .click();
  await page.getByRole("button", { name: "Create a new scope" }).click();
  await page
    .getByRole("button", { name: "Create authorization scope", exact: true })
    .click();
  await page.getByRole("checkbox", { name: /HTTP security headers/ }).check();
  await page.locator("label").filter({ hasText: "HTTP cookie security" }).click();
  await expect(
    page.getByRole("checkbox", { name: /HTTP cookie security/ }),
  ).toBeChecked();
  await page
    .getByRole("button", { name: "Run assessment", exact: true })
    .click();
  await expect(page).toHaveURL(/\/app\/assessments\//);
  await expect(
    page.getByText("completed", { exact: true }).first(),
  ).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".finding")).toHaveCount(6);
  await page.reload();
  await expect(page.locator(".finding")).toHaveCount(6);
  for (const detail of await page.locator(".finding summary").all())
    await detail.click();
  await expect(
    page.getByRole("region", { name: "Finding evidence" }),
  ).toHaveCount(6);
  await page.screenshot({
    path: "test-results/assessment-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/assessment-mobile.png",
    fullPage: true,
  });
  const id = page.url().split("/").at(-1)!;
  const results = await (
    await request.get(`/api/v1/assessments/${id}/results`)
  ).json();
  const evidence = await (
    await request.get(`/api/v1/assessments/${id}/evidence`)
  ).json();
  expect(results.result.sandbox_backend).toBe("docker");
  expect(results.result.cleanup_verified).toBe(true);
  expect(results.cleanup_pending).toBe(false);
  expect(
    evidence.evidence.map((e: { finding_id: string }) => e.finding_id).sort(),
  ).toEqual(results.findings.map((f: { id: string }) => f.id).sort());
  const output =
    JSON.stringify({ results, evidence }) +
    (await page.locator("body").innerText());
  for (const value of [
    "synthetic-theme",
    "synthetic-cross-site",
    "synthetic-secure-prefix",
    "synthetic-host-prefix",
  ])
    expect(output).not.toContain(value);
  const selector = `label=seireth.assessment=${id}`;
  expect(
    execFileSync(dockerExecutable, ["ps", "-aq", "--filter", selector], {
      encoding: "utf8",
      timeout: 20_000,
    }).trim(),
  ).toBe("");
  expect(
    execFileSync(dockerExecutable, ["network", "ls", "-q", "--filter", selector], {
      encoding: "utf8",
      timeout: 20_000,
    }).trim(),
  ).toBe("");
});

test("direct navigation renders saved text safely and keeps API and missing assets separate", async ({
  page,
  request,
}) => {
  const name = "<script>window.syntheticInjected=true</script>";
  const created = await request.post("/api/v1/projects", { data: { name } });
  expect(created.ok()).toBe(true);
  const { id } = await created.json();
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto(`/app/projects/${id}`);
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  expect(await page.evaluate(() => "syntheticInjected" in window)).toBe(false);
  for (const section of ["Targets", "Scopes", "Audit trail", "Assessments"]) {
    await page.getByRole("button", { name: section, exact: true }).click();
  }
  await expect(
    page.getByRole("heading", { name: "Assessment history" }),
  ).toBeVisible();
  expect(
    requests.every((url) => new URL(url).origin === new URL(page.url()).origin),
  ).toBe(true);
  expect(
    (
      await request.get("/app/assets/not-built.js", {
        headers: { Accept: "text/html" },
      })
    ).status(),
  ).toBe(404);
  expect(
    (
      await request.get("/api/v1/missing", { headers: { Accept: "text/html" } })
    ).status(),
  ).toBe(404);
  expect((await request.get("/health")).ok()).toBe(true);
  expect((await request.get("/openapi.json")).ok()).toBe(true);
});
