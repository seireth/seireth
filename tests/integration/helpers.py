"""Owned Docker resource helpers for integration acceptance tests."""

import subprocess


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
