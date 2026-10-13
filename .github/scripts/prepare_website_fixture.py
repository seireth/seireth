"""Connect the CI API to its controlled existing website and copy a public grant."""

import json
import subprocess
from pathlib import Path


def output(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=30).strip()


network = "seireth-ci-demo-app_default"
metadata = json.loads(output("network", "inspect", network))[0]
cidrs = [item["Subnet"] for item in metadata["IPAM"]["Config"] if item.get("Subnet")]
config = Path("artifacts/website-operator.json")
config.write_text(
    json.dumps(
        {
            "networks": {
                "browser-fixture": {"url": "http://workspace:8080/", "cidrs": cidrs}
            },
        }
    )
)
api = output("compose", "ps", "-q", "api")
subprocess.run(["docker", "network", "connect", network, api], check=True)
subprocess.run(
    ["docker", "cp", str(config), api + ":/tmp/seireth-operator.json"], check=True
)
