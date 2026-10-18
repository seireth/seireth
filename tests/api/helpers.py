"""Shared API assertions for unchanged persistence and assessment requests."""

from sqlalchemy import select


def snapshot(database):
    with database.engine.connect() as connection:
        return {
            table.name: [
                dict(row)
                for row in connection.execute(
                    select(table).order_by(table.c.id)
                ).mappings()
            ]
            for table in database.Base.metadata.sorted_tables
        }


def submission(graph):
    return {
        "project_id": graph.project.id,
        "target_id": graph.target.id,
        "url": graph.assessment.url,
        "plugins": ["http-security-headers"],
    }


def register(client, project, website):
    response = client.post(
        "/api/v1/targets",
        json={
            "project_id": project,
            "name": "owned staging",
            "kind": "website",
            "url": website.url,
            "network_profile": "fixture",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def submit(client, project, target, url, *, key="root", baseline=None, **options):
    response = client.post(
        "/api/v1/assessments",
        json={
            "project_id": project,
            "target_id": target,
            "routes": [
                {
                    "key": key,
                    "url": url,
                    "plugins": ["http-security-headers", "csp-policy"],
                    **options,
                }
            ],
            "baseline": baseline,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


def finish(client, identifier, wait_until):
    plan = client.get(f"/api/v1/assessments/{identifier}").json()["plan_snapshot"]
    result = wait_until(
        lambda: client.get(f"/api/v1/assessments/{identifier}/results").json(),
        lambda item: item["status"] in {"completed", "failed", "cancelled"},
        description="assessment result",
        timeout=plan["timeout_seconds"] + plan["cleanup_seconds"] + 5,
    )
    response = client.get(f"/api/v1/assessments/{identifier}/report")
    assert response.status_code == 200, response.text
    return result, response.json()
