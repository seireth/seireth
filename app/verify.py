"""End-to-end verification of the public MVP-0 API workflow."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

import httpx
from .config import settings


def require(response: httpx.Response, expected: int) -> dict:
    """Validate an API response and return its JSON body."""

    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} returned "
            f"{response.status_code}: {response.text}"
        )
    return response.json()


def verify(base_url: str, api_key: str | None = None) -> dict:
    """Run the complete reachable MVP-0 workflow against a running API."""

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(base_url=base_url, headers=headers, timeout=10) as client:
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
                    "owned_demo": True,
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
            200,
        )
        results = require(
            client.get(f"/api/v1/assessments/{assessment['id']}/results"),
            200,
        )
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
            "assessment.completed",
        ]
        if actions != expected_actions:
            raise RuntimeError(f"unexpected audit trail: {actions}")
        if results["status"] != "completed" or not results["findings"]:
            raise RuntimeError(f"assessment did not produce findings: {results}")
        if not results["result"]["cleanup_verified"]:
            raise RuntimeError("sandbox cleanup was not verified")
        return {
            "project": project,
            "target": target,
            "scope": scope,
            "assessment": assessment,
            "results": results,
            "audit": audit,
        }


def main() -> int:
    """Parse verification options, run the workflow, and print its JSON output."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=settings.api_base_url)
    parser.add_argument("--api-key")
    args = parser.parse_args()
    print(json.dumps(verify(args.base_url, args.api_key), indent=2, default=str))
    return 0
