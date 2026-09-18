from app.main import bounded_url


def test_scope_requires_a_path_boundary():
    assert bounded_url("https://example.test/app/login", "https://example.test/app")
    assert not bounded_url(
        "https://example.test/application", "https://example.test/app"
    )
    assert not bounded_url(
        "https://user:pass@example.test/app", "https://example.test/app"
    )
    assert not bounded_url(
        "https://example.test/app/../secret", "https://example.test/app"
    )


def test_root_scope_contains_child_paths():
    assert bounded_url("https://example.test/login", "https://example.test/")
    assert not bounded_url("https://other.test/login", "https://example.test/")
    assert not bounded_url(
        "https://example.test/%252e%252e/secret", "https://example.test/"
    )
