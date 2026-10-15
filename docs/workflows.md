# Docker releases and existing websites

Seireth checks declared HTTP responses for its header, CSP, and cookie rules.
A run records what executed, which required checks ran, and whether cleanup was
verified. A passing release verdict applies only to that declared coverage.

## Choose the source

Register **kind: docker**, an image, and a base URL to assess a fresh application
bundle. Register **kind: website**, a base URL, and no image to request an existing
deployment. Both use the same response fetcher and plugins.

Websites need no Docker daemon; Docker images must exist locally. Follow
[getting started](getting-started.md) to prepare the API and runner.

## Operator configuration and credentials

Point SEIRETH_OPERATOR_CONFIG_FILE at an operator-owned JSON file. Its sections
are requests, launches, networks, trusts, and secrets. Inspect sanitized profile
metadata at GET /api/v1/runtime/profiles and rule IDs/applicability at
GET /api/v1/plugins.

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
Certificate verification remains enabled; trust_profile adds the configured CA.
For a containerized API, mount operator files read-only and explicitly forward
the required secret environment variables. See [connection boundaries](security-model.md#enforced-boundaries).

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
python -m app.cli.commands assess --project-id PROJECT --target-id TARGET --plan routes.json --output report.json
~~~

POST /api/v1/assessments accepts the same routes with project_id, target_id, and
optional baseline. Single-URL submissions normalize to a route
named response.

Defaults are HTTP 200 and HTML. Declare JSON explicitly. An intentional redirect
uses its expected status, `media_types: []`, and `required_checks: []` to check only
the response expectation. Declare expected cookies when their presence matters.
Redirect following is off by
default. A request profile can enable at most five hops within the registered
origin and path. Reports show the chain and final response; observed URL query
values are omitted from evidence.
Redirect requests reuse the profile's headers, including an explicitly supplied
Cookie header. Cookies received in responses are never added to subsequent requests.
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

The controlled example uses PostgreSQL, an owned volume, seeded data, verified
HTTPS, and a supplied bearer token:

~~~sh
docker build -t seireth/service-fixture:local examples/service_bundle
~~~

Supply a certificate and private key for `fixture.test`, issued by a trusted CA
or a development CA whose certificate you configure below. For a disposable
local fixture, run OpenSSL outside the checkout to generate a one-day self-signed
certificate:

~~~sh
openssl req -x509 -newkey rsa:2048 -noenc -keyout fixture-key.pem -out fixture-cert.pem -days 1 -subj /CN=fixture.test -addext subjectAltName=DNS:fixture.test
~~~

The paths below must be readable by the API process; a containerized API needs
operator-managed files available inside
that container. The private key is resolved at runtime and never enters a saved
plan or report.

Add this launch configuration:

~~~json
{
  "secrets": {
    "database": {"env": "FIXTURE_DATABASE_PASSWORD"},
    "session": {"env": "FIXTURE_AUTHORIZATION"},
    "tls-certificate": {"file": "/operator/fixture-cert.pem"},
    "tls-private-key": {"file": "/operator/fixture-key.pem"}
  },
  "trusts": {"fixture-ca": {"file": "/operator/fixture-cert.pem"}},
  "requests": {
    "fixture-session": {"secret_headers": {"Authorization": "session"}}
  },
  "launches": {
    "fixture": {
      "target": {
        "depends_on": ["postgres"],
        "readiness": {"kind": "https", "port": 8080},
        "secret_environment": {
          "DATABASE_PASSWORD": "database",
          "SESSION_TOKEN": "session",
          "TLS_CERTIFICATE": "tls-certificate",
          "TLS_PRIVATE_KEY": "tls-private-key"
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

Register image seireth/service-fixture:local, URL https://fixture.test:8080/,
launch_profile fixture and trust_profile fixture-ca. Use request profile fixture-session for /private;
/before and /after demonstrate a finding and its correction. Set the two
referenced variables in the API process before starting a run.

One bundle serves every route. Services declare users, volumes/tmpfs, limits, and
readiness; [sandbox restrictions](security-model.md#enforced-boundaries) apply.
Credentials must match this freshly seeded instance. No browser login is run.

Readiness supports `tcp`, `http` and `https`. HTTPS probes use the bundle's
configured trust and preserve the target's registered Host/SNI; companion probes
use the declared service name. Certificate and hostname checks remain enabled.
Selecting `http` explicitly requests a plaintext internal probe; network
isolation does not provide encryption.

## Failures, recovery, and reports

Route-local failures allow later routes to run; cancellation, ownership loss,
the overall deadline, or preparation failure stop the plan. Findings from complete
routes become public after verified cleanup and are labelled partial when the
batch fails. Docker can retry an interrupted attempt once after cleanup; websites
never replay interrupted requests. See [recovery](architecture.md#recovery).

The dashboard and [JSON/HTML reports](assessments.md#download-assessment-reports)
show persisted routes, findings, evidence, coverage, cleanup, and verdict.

Use --baseline ASSESSMENT to compare complete runs with identical route
expectations, request/analysis context, and plugin versions. Image IDs may differ.
Incomplete or incompatible comparisons are unavailable; baselines never suppress
findings.

Limits are 20 routes, eight companion services, and 16 owned volumes.
See [timeout configuration](configuration.md#timeouts) for execution and cleanup budgets.
