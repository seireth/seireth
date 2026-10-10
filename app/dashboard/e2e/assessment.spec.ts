import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { isAbsolute } from "node:path";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import type { AssessmentReport } from "../src/api/types";

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
  context,
}, testInfo) => {
  await page.goto("/dashboard/");
  const projectName = `Browser verification ${Date.now()} <script>window.syntheticReportInjected=true</script>`;
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
  await page.getByLabel("Docker image").fill("seireth/demo-app:local");
  await page
    .getByLabel("Registered URL")
    .fill("http://demo-app:8080/cookies");
  await page
    .getByRole("button", { name: "Register target", exact: true })
    .click();
  await page.getByRole("checkbox", { name: /HTTP security headers/ }).check();
  await page.locator("label").filter({ hasText: "HTTP cookie security" }).click();
  await expect(
    page.getByRole("checkbox", { name: /HTTP cookie security/ }),
  ).toBeChecked();
  await page
    .getByRole("button", { name: "Run assessment", exact: true })
    .click();
  await expect(page).toHaveURL(/\/dashboard\/assessments\//);
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
  async function downloadReport(format: "JSON" | "HTML") {
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: `Download ${format}` }).click(),
    ]);
    expect(download.suggestedFilename()).toBe(`seireth-assessment-${id}.${format.toLowerCase()}`);
    const path = testInfo.outputPath(download.suggestedFilename());
    await download.saveAs(path);
    return { path, content: await readFile(path, "utf8") };
  }
  const jsonDownload = await downloadReport("JSON");
  const report = JSON.parse(jsonDownload.content) as AssessmentReport;
  expect(report.schema_version).toBe(1);
  expect(report.assessment.result).toEqual(results.result);
  expect(report.findings).toEqual([...results.findings].sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  expect(report.evidence).toEqual(evidence.evidence);
  const htmlDownload = await downloadReport("HTML");
  const offline = await context.newPage();
  const networkRequests: string[] = [];
  offline.on("request", (request) => {
    if (/^https?:/.test(request.url())) networkRequests.push(request.url());
  });
  await context.setOffline(true);
  try {
    await offline.goto(pathToFileURL(htmlDownload.path).href);
    await expect(offline.getByText(projectName, { exact: false })).toBeVisible();
    await expect(offline.locator(".finding")).toHaveCount(6);
    await expect(offline.getByRole("region", { name: "Finding evidence" })).toHaveCount(6);
    await expect(offline.getByText("Verified", { exact: true })).toBeVisible();
    await expect(offline.getByRole("heading", { name: "Response and check outcomes" })).toBeVisible();
    expect(await offline.locator("script, img, link, [src], [href]").count()).toBe(0);
    expect(await offline.evaluate(() => "syntheticReportInjected" in window)).toBe(false);
    expect(networkRequests).toEqual([]);
    await offline.screenshot({ path: testInfo.outputPath("report-desktop.png"), fullPage: true });
    await offline.setViewportSize({ width: 390, height: 844 });
    expect(await offline.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await offline.screenshot({ path: testInfo.outputPath("report-mobile.png"), fullPage: true });
  } finally {
    await offline.close();
    await context.setOffline(false);
  }
  const output =
    JSON.stringify({ results, evidence }) +
    (await page.locator("body").innerText()) + jsonDownload.content + htmlDownload.content;
  for (const value of [
    "synthetic-theme",
    "synthetic-cross-site",
    "synthetic-secure-prefix",
    "synthetic-host-prefix",
  ])
    expect(output).not.toContain(value);
  // An unexpected response must surface rendering failures without downloading a blank file.
  await page.route(`**/api/v1/assessments/${id}/report`, (route) => route.fulfill({
    json: { ...report, assessment: { ...report.assessment,
      result: { ...report.assessment.result, completed_at: "20261007T120000+0000" },
    } },
  }), { times: 1 });
  let failedDownloads = 0;
  const recordDownload = () => { failedDownloads++; };
  page.on("download", recordDownload);
  try {
    await page.getByRole("button", { name: "Download HTML" }).click();
    await expect(page.getByRole("alert")).toHaveText("Could not generate the HTML report.");
    expect(failedDownloads).toBe(0);
    await expect(page.getByRole("button", { name: "Download JSON" })).toBeEnabled();
    await expect(page.locator(".finding")).toHaveCount(6);
  } finally { page.off("download", recordDownload); }
  const retryDownload = await downloadReport("HTML");
  expect(retryDownload.content).toContain("SEIRETH assessment report");
  await expect(page.getByRole("alert")).toHaveCount(0);
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
  const root = await request.get("/", { maxRedirects: 0 });
  expect(root.status()).toBe(307);
  expect(root.headers().location).toBe("/dashboard/");
  for (const path of ["/app", "/app/", "/app/projects/demo"]) {
    expect(
      (await request.get(path, { headers: { Accept: "text/html" } })).status(),
    ).toBe(404);
  }
  const name = "<script>window.syntheticInjected=true</script>";
  const created = await request.post("/api/v1/projects", { data: { name } });
  expect(created.ok()).toBe(true);
  const { id } = await created.json();
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto(`/dashboard/projects/${id}`);
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  expect(await page.evaluate(() => "syntheticInjected" in window)).toBe(false);
  for (const section of ["Targets", "Audit trail", "Assessments"]) {
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
      await request.get("/dashboard/assets/not-built.js", {
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
