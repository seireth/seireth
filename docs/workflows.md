# Docker releases and existing websites

Seireth checks declared HTTP responses for its header, CSP, and cookie rules.
A run records what executed, which required checks ran, and whether cleanup was
verified. A passing release verdict applies only to that declared coverage.

## Choose the source

Register **kind: docker**, an image, and a base URL to assess a fresh application
bundle. Register **kind: website**, a base URL, and no image to request an existing
deployment. Both use the same response fetcher and plugins.

The registered target kind selects execution. Website execution runs natively
and does not require a Docker daemon. Apply migrations before startup.

Docker images must exist locally. The docker-up command builds the API and
seireth/runner:local. Native API users prepare the runner explicitly:

~~~sh
python -m app migrate
docker build --target runner -t seireth/runner:local .
~~~

## Operator configuration and credentials

Point SEIRETH_OPERATOR_CONFIG_FILE at an operator-owned JSON file. Its sections
are requests, launches, networks, trusts, and secrets. Inspect sanitized profile
metadata at GET /api/v1/runtime/profiles and rule IDs/applicability at
GET /api/v1/plugin-rules.

~~~json
{
  "secrets": {"staging-session": {"env": "STAGING_AUTHORIZATION"}},
  "requests": {
    "authenticated": {"secret_headers": {"Authorization": "staging-session"}}
  },
  "networks": {
    "staging": {
      "url": "https://staging.example.test/",
      "cidrs": ["10.42.0.0/24"]
    }
  },
  "trusts": {"staging-ca": {"file": "/operator/staging-ca.pem"}}
}
~~~

Set STAGING_AUTHORIZATION in the **API process** to the complete header value,
such as Bearer followed by the token. Cookies use a secret Cookie header.
A secret reference can instead use a file entry pointing at a readable session
file. Put credentials and API keys in secret references, never literal headers
or environment entries.

Public HTTP(S) destinations are allowed within the target boundary. Private
staging requires a matching network_profile and approved address range.
Addresses are validated and pinned before connecting; metadata, link-local, and
Seireth/Docker control endpoints are blocked. Requests ignore environment proxies.
Certificate verification remains enabled; trust_profile adds the configured CA.
For a containerized API, mount operator files read-only and explicitly forward
the required secret environment variables.

Submission freezes public profile contents, reference names, plugin versions,
CA contents, and Docker image IDs. Editing a request profile does not change a
queued run. Secrets resolve at attempt start, and current private-network grants
are checked on each connection.

## Declare the release coverage

Save this as routes.json, using URLs inside the registered target:

~~~json
{
  "routes": [
    {
      "key": "dashboard",
      "url": "https://staging.example.test/dashboard",
      "plugins": ["http-security-headers", "csp-policy"],
      "request_profile": "authenticated",
      "expected": {"statuses": [200], "media_types": ["text/html"]}
    },
    {
      "key": "session",
      "url": "https://staging.example.test/session",
      "plugins": ["cookie-security"],
      "analysis": {
        "session_cookies": ["session"],
        "expected_cookies": ["session"]
      },
      "expected": {"statuses": [200], "media_types": ["text/html"]}
    },
    {
      "key": "api",
      "url": "https://staging.example.test/api/summary",
      "plugins": ["http-security-headers"],
      "request_profile": "authenticated",
      "expected": {"statuses": [200], "media_types": ["application/json"]}
    }
  ]
}
~~~

~~~sh
python -m app assess --project-id PROJECT --target-id TARGET --plan routes.json --output report.json
~~~

POST /api/v1/assessments accepts the same routes with project_id, target_id, and
optional baseline. Existing url-plus-plugins submissions normalize to a route
named response.

Defaults are HTTP 200 and HTML. Declare JSON explicitly. An intentional redirect
uses its expected status and an empty media_types list; declare an expected
response cookie when cookie coverage is intended. Redirect following is off by
default. A request profile can enable at most five hops within the registered
origin and path. Reports show the chain and final response; observed URL query
values are omitted from evidence.
The expected final URL defaults to the requested URL. Set expected.final_url
explicitly for an intentional destination; a followed login redirect otherwise
blocks the gate even when the login page has good security headers.

Required checks derive from representation and cookie expectations. An explicit
required_checks list selects catalogue IDs in plugin:rule form. An inferred empty
set is incomplete. An explicit empty list requires only the response expectation.

The strict verdict blocks on **any finding**, failed required checks, missing or
inconclusive required coverage, unexpected responses, unsuccessful execution,
or unverified cleanup. The CLI saves its report first, then returns
0 for pass, 1 for operational failure, or 2 for a policy block. The verify command
checks the lifecycle and evidence; it deliberately does not implement this gate.

## Reproduce a configured Docker application

The controlled example uses PostgreSQL, an owned volume, seeded data, and a
supplied bearer token:

~~~sh
docker build -t seireth/service-fixture:local examples/service_bundle
~~~

Add this launch configuration:

~~~json
{
  "secrets": {
    "database": {"env": "FIXTURE_DATABASE_PASSWORD"},
    "session": {"env": "FIXTURE_AUTHORIZATION"}
  },
  "requests": {
    "fixture-session": {"secret_headers": {"Authorization": "session"}}
  },
  "launches": {
    "fixture": {
      "target": {
        "depends_on": ["postgres"],
        "secret_environment": {
          "DATABASE_PASSWORD": "database",
          "SESSION_TOKEN": "session"
        }
      },
      "services": {
        "postgres": {
          "image": "postgres:18-trixie",
          "uid": 999,
          "gid": 999,
          "environment": {"PGDATA": "/var/lib/postgresql/18/docker"},
          "secret_environment": {"POSTGRES_PASSWORD": "database"},
          "tmpfs": ["/var/run/postgresql"],
          "volumes": [{"name": "database", "path": "/var/lib/postgresql"}],
          "readiness": {"kind": "tcp", "port": 5432}
        }
      }
    }
  }
}
~~~

Register image seireth/service-fixture:local, URL http://fixture.test:8080/, and
launch_profile fixture. Use request profile fixture-session for /private;
/before and /after demonstrate a finding and its correction. Set the two
referenced variables in the API process before starting a run.

One bundle serves every route in an attempt. Host/TLS use the original hostname
while connections route internally. Services have explicit users, read-only
roots, declared volumes/tmpfs, limits, and readiness. A restricted journaled
helper initializes fresh volume ownership. Host binds, shared/external volumes,
and undeclared image volumes are rejected. Credentials must match this freshly
seeded instance; sessions from another deployment are not transferred.
No browser login is run.

## Failures, recovery, and reports

Routes commit only after all selected plugins succeed. Route-local failures let
later routes run. Cancellation, ownership loss, the overall deadline, or
preparation failure stop the plan. Complete routes from a failed batch remain
clearly partial and become public only after verified cleanup.

Execution outcome, coverage, cleanup, and verdict are separate. Reconciliation
can release valid evidence without turning a failed run into a pass. Unknown
Docker creation/removal stays pending; elapsed time cannot certify cleanup.
Native HTTP recovery requires socket closure acknowledgement or confirmed process
exit and never automatically replays website requests. Docker retains one crash
retry using a fresh bundle after verified cleanup. Attempts are never merged.

Reports use the single current schema, version 1. Reports come from
persisted results and remain available after restart. The dashboard shows source,
routes, coverage, partial execution, cleanup, verdict, comparison, findings,
evidence, and JSON/HTML downloads.

Use --baseline ASSESSMENT to compare complete runs with identical route
expectations, request/analysis context, and plugin versions. Image IDs may differ.
Incomplete or incompatible comparisons are unavailable; baselines never suppress
findings.

Limits are 20 routes, eight companion services, and 16 owned volumes. Requests
default to 10 seconds. Plans receive startup budget plus 15 seconds per route,
capped at 900 seconds; single-URL requests retain their configured deadline.
Cleanup gets a separate 60-second foreground budget and continues through
reconciliation when needed. Analyzers remain trusted, bounded, cooperative
built-ins.
