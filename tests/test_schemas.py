import pytest
from pydantic import ValidationError

from app.schemas import (
    AssessmentCreate,
    EvidenceOut,
    ProjectCreate,
    ScopeCreate,
    TargetCreate,
)


@pytest.mark.parametrize("image", [None, "", "a" * 300, "a" * 301])
def test_target_image_input_respects_storage_limit(image):
    payload = {"project_id": "project", "name": "target", "image": image}
    if image is not None and len(image) > 300:
        with pytest.raises(ValidationError) as error:
            TargetCreate(**payload)
        assert error.value.errors()[0]["loc"] == ("image",)
    else:
        assert TargetCreate(**payload).image == image


@pytest.mark.parametrize(
    "selection",
    [{}, {"plugins": None}, {"plugins": []}, {"plugins": "security-headers"}],
)
def test_assessment_requires_explicit_nonempty_plugins(selection):
    with pytest.raises(ValidationError) as error:
        AssessmentCreate(
            project_id="project", target_id="target", scope_id="scope", **selection
        )
    assert error.value.errors()[0]["loc"] == ("plugins",)


def sized_url(length, *, normalized_growth=False):
    prefix = "https://example.test?" if normalized_growth else "https://example.test/"
    return prefix + "a" * (length - len(prefix))


@pytest.mark.parametrize(
    "schema,field,base",
    [
        (TargetCreate, "url", {"project_id": "p", "name": "target"}),
        (
            ScopeCreate,
            "allowed_url",
            {"project_id": "p", "target_id": "t", "expires_at": "2099-01-01T00:00:00Z"},
        ),
    ],
)
@pytest.mark.parametrize(
    "length,growth,accepted",
    [
        pytest.param(500, False, True, id="exact-limit"),
        pytest.param(500, True, False, id="normalization-growth"),
        pytest.param(501, False, False, id="over-limit"),
    ],
)
def test_persisted_urls_are_bounded_after_normalization(
    schema, field, base, length, growth, accepted
):
    payload = {**base, field: sized_url(length, normalized_growth=growth)}
    if accepted:
        assert len(str(getattr(schema(**payload), field))) == 500
    else:
        with pytest.raises(ValidationError) as error:
            schema(**payload)
        assert error.value.errors()[0]["loc"] == (field,)
        if growth:
            assert "normalized URL" in str(error.value)


def test_assessment_rejects_unknown_fields():
    with pytest.raises(ValidationError) as error:
        AssessmentCreate(
            project_id="p",
            target_id="t",
            scope_id="s",
            plugins=["security-headers"],
            unexpected=True,
        )
    assert error.value.errors()[0]["type"] == "extra_forbidden"
    assert error.value.errors()[0]["loc"] == ("unexpected",)


@pytest.mark.parametrize(
    "schema,base", [(ProjectCreate, {}), (TargetCreate, {"project_id": "p"})]
)
@pytest.mark.parametrize("length", [200, 201])
def test_names_respect_storage_limit(schema, base, length):
    if length == 200:
        assert schema(name="n" * length, **base).name == "n" * length
    else:
        with pytest.raises(ValidationError) as error:
            schema(name="n" * length, **base)
        assert error.value.errors()[0]["loc"] == ("name",)


@pytest.fixture(
    params=[
        {"header": "x-content-type-options"},
        {"header": "content-security-policy"},
        {"header": "x-frame-options"},
        {
            "header": "set-cookie",
            "cookie_name": "cross",
            "rule": "samesite-none-without-secure",
            "samesite": "none",
            "secure": False,
        },
        {
            "header": "set-cookie",
            "cookie_name": "__sEcUrE-session",
            "rule": "secure-prefix",
            "secure": True,
            "https": False,
        },
        {
            "header": "set-cookie",
            "cookie_name": "__hOsT-session",
            "rule": "host-prefix",
            "secure": True,
            "https": True,
            "domain_present": True,
            "root_path": False,
        },
    ]
)
def public_evidence(request):
    return {
        "id": "evidence-id",
        "finding_id": "finding-id",
        "kind": "http-response",
        "data": {"url": "https://example.test/app", **request.param},
    }


def test_public_evidence_payloads_round_trip_without_changing_fields(public_evidence):
    evidence = EvidenceOut(**public_evidence)
    assert evidence.model_dump(mode="json") == public_evidence
    assert EvidenceOut.model_validate_json(evidence.model_dump_json()) == evidence


@pytest.mark.parametrize("field", ["cookie_value", "raw_header", "unexpected"])
def test_public_evidence_rejects_extra_fields_without_echoing_values(
    public_evidence, field
):
    public_evidence["data"][field] = "synthetic-secret-not-for-output"
    with pytest.raises(ValidationError) as error:
        EvidenceOut(**public_evidence)
    assert "synthetic-secret-not-for-output" not in str(error.value)


def test_every_public_evidence_field_is_required(public_evidence):
    for field in public_evidence["data"]:
        partial = {
            **public_evidence,
            "data": {
                name: value
                for name, value in public_evidence["data"].items()
                if name != field
            },
        }
        with pytest.raises(ValidationError):
            EvidenceOut(**partial)
    for field in ("id", "finding_id", "kind", "data"):
        with pytest.raises(ValidationError):
            EvidenceOut(
                **{
                    name: value
                    for name, value in public_evidence.items()
                    if name != field
                }
            )


@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_public_evidence_booleans_are_strict(value):
    for field in ("secure", "https", "domain_present", "root_path"):
        data = {
            "url": "https://example.test/",
            "header": "set-cookie",
            "cookie_name": "__Host-session",
            "rule": "host-prefix",
            "secure": True,
            "https": True,
            "domain_present": True,
            "root_path": False,
            field: value,
        }
        with pytest.raises(ValidationError):
            EvidenceOut(id="e", finding_id="f", kind="http-response", data=data)


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "ftp://example.test/"},
        {"url": 123},
        {"url": "https://example.test/" + "a" * 501},
        {"header": "Set-Cookie"},
        {"cookie_name": ""},
        {"cookie_name": 123},
        {"rule": "unknown-rule"},
        {"samesite": "None"},
    ],
)
def test_public_cookie_evidence_rejects_invalid_values(changes):
    data = {
        "url": "https://example.test/",
        "header": "set-cookie",
        "cookie_name": "cross",
        "rule": "samesite-none-without-secure",
        "samesite": "none",
        "secure": False,
        **changes,
    }
    with pytest.raises(ValidationError):
        EvidenceOut(id="e", finding_id="f", kind="http-response", data=data)
