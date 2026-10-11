import { test, expect } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

type Fixture = {
  name: string;
  policies: string[];
  checks: [string, string, string];
  network: boolean;
  inline: boolean;
  handler: boolean;
  eval?: boolean;
};

const pass: Fixture["checks"] = ["passed", "passed", "passed"];
const fail: Fixture["checks"] = ["failed", "failed", "failed"];
const permissive = "script-src https: 'unsafe-inline' 'unsafe-eval'";

// These expectations are authored against browser behavior, independently of Python.
const fixtures: Fixture[] = [
  { name: "wildcard sources", policies: ["script-src * 'unsafe-inline' 'unsafe-eval'"], checks: fail, network: true, inline: true, handler: true, eval: true },
  { name: "HTTP sources upgrade to HTTPS", policies: ["script-src http: 'unsafe-inline' 'unsafe-eval'"], checks: fail, network: true, inline: true, handler: true, eval: true },
  { name: "global HTTPS hosts", policies: ["script-src https://* 'unsafe-inline' 'unsafe-eval'"], checks: fail, network: true, inline: true, handler: true, eval: true },
  { name: "global HTTP hosts upgrade to HTTPS", policies: ["script-src http://* 'unsafe-inline' 'unsafe-eval'"], checks: fail, network: true, inline: true, handler: true, eval: true },
  { name: "nonce grammar is case insensitive", policies: ["script-src 'self' 'unsafe-inline' 'NONCE-YWJj'"], checks: pass, network: false, inline: false, handler: false, eval: false },
  { name: "malformed nonce does not suppress inline", policies: ["script-src 'self' 'unsafe-inline' 'nonce-a==='"], checks: ["passed", "failed", "passed"], network: false, inline: true, handler: true, eval: false },
  { name: "Trusted Types keeps eval inconclusive", policies: ["script-src 'self' 'unsafe-eval'; require-trusted-types-for 'script'"], checks: ["passed", "passed", "inconclusive"], network: false, inline: false, handler: false, eval: false },
  { name: "non-ASCII script directive is discarded", policies: ["script-src 'none' \u00e9"], checks: fail, network: true, inline: true, handler: true, eval: true },
  { name: "non-ASCII default directive is discarded", policies: ["default-src 'none' \u00e9"], checks: fail, network: true, inline: true, handler: true, eval: true },
  { name: "non-ASCII directive does not hide a later duplicate", policies: ["script-src 'none' \u00e9; " + permissive], checks: fail, network: true, inline: true, handler: true, eval: true },
  { name: "discarded directive keeps context-specific controls", policies: ["script-src 'none' \u00e9; script-src-elem 'self'"], checks: ["passed", "failed", "failed"], network: false, inline: false, handler: true, eval: true },
  { name: "discarded directive uses default fallback", policies: ["default-src 'self'; script-src 'none' \u00e9"], checks: pass, network: false, inline: false, handler: false, eval: false },
  { name: "non-ASCII sandbox cannot restrict scripts", policies: [permissive + "; sandbox \u00e9"], checks: fail, network: true, inline: true, handler: true, eval: true },
  { name: "non-ASCII Trusted Types requirement is discarded", policies: ["script-src 'self' 'unsafe-eval'; require-trusted-types-for 'script' \u00e9"], checks: ["passed", "passed", "failed"], network: false, inline: false, handler: false, eval: true },
  { name: "Trusted Types eval interaction in one policy", policies: ["script-src 'self' 'trusted-types-eval'; require-trusted-types-for 'script'"], checks: ["passed", "passed", "inconclusive"], network: false, inline: false, handler: false, eval: true },
  { name: "Trusted Types eval interaction across policies", policies: ["script-src 'self' 'trusted-types-eval'", "require-trusted-types-for 'script'"], checks: ["passed", "passed", "inconclusive"], network: false, inline: false, handler: false, eval: true },
  { name: "Trusted Types policy order does not affect eval", policies: ["require-trusted-types-for 'script'", "script-src 'self' 'trusted-types-eval'"], checks: ["passed", "passed", "inconclusive"], network: false, inline: false, handler: false, eval: true },
  { name: "source-list restriction cannot settle Trusted Types eval interaction", policies: ["require-trusted-types-for 'script'", "script-src 'self' 'trusted-types-eval'", "script-src 'self'"], checks: ["passed", "passed", "inconclusive"], network: false, inline: false, handler: false, eval: true },
  { name: "sandbox settles Trusted Types eval interaction", policies: ["require-trusted-types-for 'script'", "script-src 'self' 'trusted-types-eval'", "sandbox"], checks: pass, network: false, inline: false, handler: false },
  { name: "overridden default does not enable Trusted Types eval", policies: ["require-trusted-types-for 'script'", "default-src 'self' 'trusted-types-eval'; script-src 'self'"], checks: pass, network: false, inline: false, handler: false, eval: false },
  { name: "permissive", policies: [permissive], checks: fail, network: true, inline: true, handler: true, eval: true },
  { name: "missing script directives", policies: ["frame-ancestors 'none'"], checks: fail, network: true, inline: true, handler: true, eval: true },
  { name: "self only", policies: ["script-src 'self'"], checks: pass, network: false, inline: false, handler: false, eval: false },
  { name: "default fallback", policies: ["default-src 'self'"], checks: pass, network: false, inline: false, handler: false, eval: false },
  { name: "empty script directive", policies: ["script-src"], checks: pass, network: false, inline: false, handler: false },
  { name: "nonce suppresses inline but not HTTPS", policies: ["script-src https: 'unsafe-inline' 'nonce-YWJj'"], checks: ["failed", "passed", "passed"], network: true, inline: false, handler: false, eval: false },
  { name: "hash suppresses unsafe inline", policies: ["script-src 'self' 'unsafe-inline' 'sha256-YWJj'"], checks: pass, network: false, inline: false, handler: false, eval: false },
  { name: "strict dynamic", policies: ["script-src https: 'unsafe-inline' 'nonce-YWJj' 'strict-dynamic'"], checks: pass, network: false, inline: false, handler: false, eval: false },
  { name: "strict dynamic without nonce", policies: ["script-src https: 'unsafe-inline' 'strict-dynamic'"], checks: pass, network: false, inline: false, handler: false },
  { name: "first duplicate restricts", policies: ["script-src 'self'; script-src https: 'unsafe-inline' 'unsafe-eval'"], checks: pass, network: false, inline: false, handler: false, eval: false },
  { name: "first duplicate permits", policies: [permissive + "; script-src 'none'"], checks: fail, network: true, inline: true, handler: true, eval: true },
  { name: "additional restrictive policy", policies: [permissive, "script-src 'self'"], checks: pass, network: false, inline: false, handler: false, eval: false },
  { name: "different inline contexts intersect", policies: ["script-src 'self' 'unsafe-inline'; script-src-attr 'none'", "script-src 'self'; script-src-attr 'unsafe-inline'"], checks: pass, network: false, inline: false, handler: false, eval: false },
  { name: "event handler override", policies: ["script-src 'self'; script-src-attr 'unsafe-inline'"], checks: ["passed", "failed", "passed"], network: false, inline: false, handler: true, eval: false },
  { name: "element override keeps eval on script-src", policies: ["script-src 'self' 'unsafe-eval'; script-src-elem 'self' 'unsafe-inline'"], checks: ["passed", "failed", "failed"], network: false, inline: true, handler: false, eval: true },
  { name: "wasm permission does not permit JS eval", policies: ["script-src 'self' 'wasm-unsafe-eval'"], checks: pass, network: false, inline: false, handler: false, eval: false },
  { name: "sandbox blocks scripts", policies: [permissive + "; sandbox"], checks: pass, network: false, inline: false, handler: false },
  { name: "sandbox allows scripts", policies: [permissive + "; sandbox allow-scripts"], checks: fail, network: true, inline: true, handler: true, eval: true },
  { name: "unsupported data sources remain inconclusive", policies: ["script-src 'self' data:"], checks: ["inconclusive", "passed", "passed"], network: false, inline: false, handler: false, eval: false },
];

const root = fileURLToPath(new URL("../../../", import.meta.url));
const python = process.env.SEIRETH_TEST_PYTHON ??
  join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const analyze = [
  "import json,sys",
  "from app.plugins.base import HttpObservation",
  "from app.plugins.csp_policy import analyze",
  "fields=json.load(sys.stdin)",
  "observation=HttpObservation(url='https://csp-fixture.test/page',status_code=200,headers={'content-type':['text/html'],'content-security-policy':fields})",
  "print(json.dumps([check.status for check in analyze(observation).checks]))",
].join("\n");

for (const fixture of fixtures) {
  test("CSP enforcement: " + fixture.name, async ({ page }) => {
    const result = spawnSync(python, ["-c", analyze], {
      cwd: root, input: JSON.stringify(fixture.policies), encoding: "utf8", timeout: 10_000,
    });
    expect(result.error).toBeUndefined();
    expect(result.status, result.stderr).toBe(0);
    expect(JSON.parse(result.stdout)).toEqual(fixture.checks);

    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/page") {
        await route.fulfill({
          status: 200,
          headers: { "content-type": "text/html", "content-security-policy": fixture.policies.join(", ") },
          body: `<!doctype html><html><body>
            <script src="https://script-origin.invalid/probe.js"></script>
            <script>window.cspInline = true</script>
            <script nonce="YWJj" src="/harness.js"></script>
            <button onclick="window.cspHandler = true">Probe handler</button>
          </body></html>`,
        });
      } else if (url.hostname === "script-origin.invalid" && url.pathname === "/probe.js") {
        await route.fulfill({ contentType: "text/javascript", body: "window.cspNetwork = true;" });
      } else if (url.hostname === "csp-fixture.test" && url.pathname === "/harness.js") {
        await route.fulfill({
          contentType: "text/javascript",
          body: "window.cspEvalAttempted = true; try { eval('window.cspEval = true'); } catch {}",
        });
      } else {
        await route.fulfill({ status: 404, body: "" });
      }
    });
    await page.goto("https://csp-fixture.test/page", { waitUntil: "load" });
    await page.getByRole("button", { name: "Probe handler" }).click();
    // DevTools execution can bypass CSP: only read flags here.
    const flags = await page.evaluate(() => {
      const values = window as unknown as Record<string, unknown>;
      return {
        network: values.cspNetwork === true, inline: values.cspInline === true,
        handler: values.cspHandler === true, eval: values.cspEval === true,
        attempted: values.cspEvalAttempted === true,
      };
    });
    expect(flags.network).toBe(fixture.network);
    expect(flags.inline).toBe(fixture.inline);
    expect(flags.handler).toBe(fixture.handler);
    if (fixture.eval !== undefined) {
      expect(flags.attempted).toBe(true);
      expect(flags.eval).toBe(fixture.eval);
    }
  });
}
