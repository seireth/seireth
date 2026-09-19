"""End-to-end verification of the public MVP-0 API workflow."""

from __future__ import annotations

import argparse
import math
import time
from datetime import datetime, timedelta, timezone

import httpx


def require(response: httpx.Response, expected: int) -> dict:
    """Validate an API response and return its JSON body."""

    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} returned "
            f"{response.status_code}: {response.text}"
        )
    return response.json()


def positive_timeout(value: str) -> float:
    """Parse a finite, positive polling timeout for either CLI entry point."""
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and greater than zero")
    return timeout


def wait_for_results(
    client: httpx.Client, assessment_id: str, timeout_seconds: float
) -> dict:
    """Poll to a terminal state within a monotonic deadline."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout must be finite and greater than zero")
    deadline = time.monotonic() + timeout_seconds
    results = None
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            results = require(
                client.get(
                    f"/api/v1/assessments/{assessment_id}/results",
                    timeout=min(10, remaining),
                ),
                200,
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"assessment {assessment_id} polling request timed out; last response: {results}"
            ) from exc
        if results["status"] in {"completed", "failed", "cancelled"}:
            return results
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
    raise RuntimeError(
        f"assessment {assessment_id} did not finish within {timeout_seconds:g}s; "
        f"last response: {results}"
    )


def verify(
    base_url: str, timeout_seconds: float = 120, expected_backend: str | None = None
) -> dict:
    """Run the complete reachable MVP-0 workflow against a running API."""

    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout must be finite and greater than zero")
    with httpx.Client(base_url=base_url, timeout=10) as client:
        require(client.get("/health"), 200)
        project = require(
            client.post("/api/v1/projects", json={"name": "MVP-0 verification"}),
            200,
        )
        target = require(
            client.post(
                "/api/v1/targets",
                json={
                    "project_id": project["id"],
                    "name": "Owned demo target",
                    "url": "http://demo-target:8080",
                },
            ),
            200,
        )
        scope = require(
            client.post(
                "/api/v1/authorization-scopes",
                json={
                    "project_id": project["id"],
                    "target_id": target["id"],
                    "allowed_url": "http://demo-target:8080",
                    "expires_at": (
                        datetime.now(timezone.utc) + timedelta(minutes=15)
                    ).isoformat(),
                },
            ),
            200,
        )
        assessment = require(
            client.post(
                "/api/v1/assessments",
                json={
                    "project_id": project["id"],
                    "target_id": target["id"],
                    "scope_id": scope["id"],
                    "profile": "passive",
                },
            ),
            202,
        )
        results = wait_for_results(client, assessment["id"], timeout_seconds)
        if results["status"] != "completed" or not results["findings"]:
            raise RuntimeError(f"assessment did not produce findings: {results}")
        if not results["result"]["cleanup_verified"]:
            raise RuntimeError("sandbox cleanup was not verified")
        if (
            expected_backend
            and results["result"]["sandbox_backend"] != expected_backend
        ):
            raise RuntimeError(f"expected {expected_backend} backend, got: {results}")
        audit = require(
            client.get(f"/api/v1/projects/{project['id']}/audit-events"),
            200,
        )
        actions = [event["action"] for event in audit]
        expected_actions = [
            "project.created",
            "target.registered",
            "scope.authorized",
            "assessment.queued",
            "assessment.running",
            "assessment.completed",
        ]
        if actions != expected_actions:
            raise RuntimeError(f"unexpected audit trail: {actions}")
        return {
            "project": project,
            "target": target,
            "scope": scope,
            "assessment": assessment,
            "results": results,
            "audit": audit,
        }
