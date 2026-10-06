import pytest

from app.assessments.policy import bounded_url

BASE = "https://example.test/app"


@pytest.mark.parametrize(
    "candidate,registered",
    [
        pytest.param(BASE, BASE, id="exact-path"),
        pytest.param(BASE + "/login", BASE, id="child-path"),
        pytest.param("https://example.test/login", "https://example.test/", id="root"),
        pytest.param("https://example.test:443/app", BASE, id="default-https-port"),
        pytest.param(
            "http://example.test:80/app",
            "http://example.test/app",
            id="default-http-port",
        ),
        pytest.param("https://EXAMPLE.test/app", BASE, id="host-case"),
        pytest.param(
            BASE + "/login?next=home", BASE + "/", id="query-and-trailing-slash"
        ),
    ],
)
def test_target_boundary_accepts_bounded_urls(candidate, registered):
    assert bounded_url(candidate, registered)


@pytest.mark.parametrize(
    "candidate,registered",
    [
        pytest.param("https://other.test/app", BASE, id="host"),
        pytest.param("http://example.test/app", BASE, id="scheme"),
        pytest.param("https://example.test:444/app", BASE, id="port"),
        pytest.param("https://example.test/application", BASE, id="path-prefix"),
        pytest.param(BASE + "/../secret", BASE, id="parent-path"),
        pytest.param(BASE + "/./login", BASE, id="dot-path"),
        pytest.param(BASE + "/%2e%2e/secret", BASE, id="encoded-traversal"),
        pytest.param(
            "https://example.test/%252e%252e/secret",
            "https://example.test/",
            id="double-encoding",
        ),
        pytest.param(BASE + "\\secret", BASE, id="backslash"),
        pytest.param(BASE + "/%5csecret", BASE, id="encoded-backslash"),
        pytest.param("https://example.test:invalid/app", BASE, id="invalid-port"),
        pytest.param("https://example.test:65536/app", BASE, id="oversized-port"),
        pytest.param("ftp://example.test/app", BASE, id="unsupported-scheme"),
        pytest.param("/app", BASE, id="missing-origin"),
    ],
)
def test_target_boundary_rejects_unbounded_urls(candidate, registered):
    assert not bounded_url(candidate, registered)


@pytest.mark.parametrize("scheme,default_port", [("http", 80), ("https", 443)])
@pytest.mark.parametrize("explicit_default", [False, True])
@pytest.mark.parametrize("zero_port_side", ["candidate", "registered"])
def test_target_boundary_distinguishes_zero_port_from_default(
    scheme, default_port, explicit_default, zero_port_side
):
    zero = f"{scheme}://example.test:0/app"
    suffix = f":{default_port}" if explicit_default else ""
    default = f"{scheme}://example.test{suffix}/app"
    candidate, registered = (
        (zero, default) if zero_port_side == "candidate" else (default, zero)
    )
    assert not bounded_url(candidate, registered)


@pytest.mark.parametrize(
    "unsafe",
    [
        "https://user:pass@example.test/app",
        BASE + "#fragment",
        "https://example.test/app/../secret",
        BASE + "\\secret",
        "https://example.test:invalid/app",
        "https://[invalid/app",
    ],
)
@pytest.mark.parametrize("side", ["candidate", "registered"])
def test_target_boundary_rejects_unsafe_components_on_either_url(unsafe, side):
    candidate, registered = (unsafe, BASE) if side == "candidate" else (BASE, unsafe)
    assert not bounded_url(candidate, registered)
