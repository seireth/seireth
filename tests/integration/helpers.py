"""Owned Docker resource helpers for integration acceptance tests."""

import subprocess


def submit_docker_assessment(client, path, plugins, *, image="seireth/demo-app:local"):
    def post(endpoint, payload):
        response = client.post("/api/v1/" + endpoint, json=payload)
        response.raise_for_status()
        return response.json()

    project = post("projects", {"name": "Docker lifecycle"})
    target = post(
        "targets",
        {
            "project_id": project["id"],
            "name": "fixture",
            "image": image,
            "url": "http://demo-app:8080/",
        },
    )
    return target, post(
        "assessments",
        {
            "project_id": project["id"],
            "target_id": target["id"],
            "url": target["url"] + path.lstrip("/"),
            "plugins": plugins,
        },
    )


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=20).strip()


def remove_assessment_resources(assessment_id):
    if assessment_id:
        selector = f"label=seireth.assessment={assessment_id}"
        for args, removal in (
            (["ps", "-aq"], ["rm", "-f"]),
            (["volume", "ls", "-q"], ["volume", "rm"]),
            (["network", "ls", "-q"], ["network", "rm"]),
        ):
            for identity in docker(*args, "--filter", selector).splitlines():
                docker(*removal, identity)
