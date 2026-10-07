# Northstar Workspace plugin demo

One runnable ticket application exercises both current plugins. Its 42 header
scenarios cover protected and misconfigured pages, JSON, assets, redirects, errors,
repeated headers, policy precedence, ordered MIME options, bodyless responses,
and missing/malformed/conflicting content types. `/cookies` preserves
the three cookie findings and six combined findings; `/cookies/protected` yields
zero findings with either or both plugins. `/slow` delays 1.5 seconds for
cancellation and crash recovery tests. Tickets are synthetic and reset per instance.

## Build and preview

From the repository root:

```bash
docker compose -f examples/demo_app/compose.yml up -d --build --wait
python -m app docker-up
```

Open [Northstar Workspace](http://127.0.0.1:8081/) and its
[plugin lab](http://127.0.0.1:8081/lab). The preview binds to loopback only. Without
Docker, `python -m examples.demo_app.server` runs the same preview.

Seireth assesses separate disposable instances of `seireth/demo-app:local`.
Register the base URL `http://demo-app:8080/`, then choose the response path in
**Assessment URL**. The preview address is for manual application actions.
No Seireth code or environment changes are needed to register another local image.

## Verify and save the project

```bash
python -m examples.demo_app.verify --output artifacts/demo-app.json
```

The verifier creates one **Northstar Workspace | Plugin demo** project and one
target. It runs all 42 header cases and both cookie paths with header-only,
cookie-only, and combined selections: 48 assessments. Expected results are grouped
by plugin in `scenarios.py`. Verification requires exact findings by stable rule
ID, declared response context, all three check outcomes and reasons, evidence URLs
and finding associations, redacted cookie evidence, remediation, audit events,
and verified resource removal. The report includes links to saved assessments.

For manual testing, use `--register-only`; select the saved target, response URL,
and plugins in the GUI. For a smaller run:

```bash
python -m examples.demo_app.verify --case / --case /cookies --case /cookies/protected
python -m app verify --image seireth/demo-app:local --target-url http://demo-app:8080/cookies/protected --plugins http-security-headers cookie-security --expected-backend docker
```

`--base-url` chooses the API address. `--skip-resource-check` supports an API using
a different daemon while still requiring its cleanup verification. Builds and
pulls are explicit operator actions; assessments use `--pull=never`.

| Response                                                                         | Header findings   | Cookie findings |
| -------------------------------------------------------------------------------- | ----------------- | --------------- |
| `/`, `/tickets`, `/account`, `/api/tickets`, `/assets/app.css`, `/assets/app.js` | 0                 | 0               |
| `/lab/missing-all`, `/errors/not-found`, `/slow`                                 | 3                 | 0               |
| `/login`, `/lab/no-content`                                                      | 0 (all skipped)   | 0               |
| `/lab/report-only`                                                              | 2                 | 0               |
| `/lab/json-unprotected`, `/lab/css-unprotected`                                  | 1 (`nosniff`)     | 0               |
| `/lab/unknown-type`, `/lab/malformed-type`, `/lab/conflicting-types`               | 1 (`nosniff`); CSP/framing inconclusive | 0 |
| `/lab/csp-wildcard`                                                              | 1 framing finding | 0               |
| `/cookies`                                                                       | 3                 | 3               |
| `/cookies/protected`                                                             | 0                 | 0               |

JSON and asset responses skip CSP/framing; redirects skip every header rule
without following the destination. Each assessment inspects one response using
declared response metadata. The ticket workflow is covered separately
by browser tests. Zero findings means no covered violations were found; neither
plugin certifies the application or fully validates CSP or browser cookie policy.

## Validate and stop

```bash
python -m pytest tests/examples/test_demo_app_verify.py tests/plugins
docker compose -f examples/demo_app/compose.yml down
```

Demo unit tests check the verifier's acceptance and failure decisions. The demo
application is excluded from Python and SonarQube coverage requirements.

Stopping the preview retains Seireth's database. Rebuild the demo after source
changes. CI builds this image and runs plugin, browser, cancellation, and crash
recovery verification, including cleanup when the target image is removed.
