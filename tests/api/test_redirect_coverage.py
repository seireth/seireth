"""Following a login redirect cannot satisfy the protected-route expectation."""

import json

from tests.api.helpers import finish, register, submit
from tests.website import configure


def test_followed_login_redirect_is_incomplete_until_final_url_is_declared(
    client, project, website, tmp_path, monkeypatch, wait_until
):
    path = configure(monkeypatch, tmp_path, website)
    config = json.loads(path.read_text())
    config["requests"]["follow"] = {"follow_redirects": True}
    path.write_text(json.dumps(config))
    website.handler.corrected = True
    target = register(client, project, website)
    identifier = submit(
        client, project, target, website.url + "private", request_profile="follow"
    )
    result, report = finish(client, identifier, wait_until)
    assert result["status"] == "completed"
    assert result["result"]["verdict"]["status"] == "blocked"
    assert not result["result"]["coverage"]["complete"]
    assert result["result"]["routes"][0]["response"]["url"] == website.url + "login"
    assert len(result["result"]["routes"][0]["response"]["redirects"]) == 1
    assert report["findings"] == []
    identifier = submit(
        client,
        project,
        target,
        website.url + "private",
        request_profile="follow",
        expected={
            "statuses": [200],
            "media_types": ["text/html"],
            "final_url": website.url + "login",
        },
    )
    result, _ = finish(client, identifier, wait_until)
    assert result["result"]["verdict"]["status"] == "pass"
