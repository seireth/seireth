import pytest
from pydantic import ValidationError

from app.api.schemas import (
    AssessmentCreate,
    EvidenceOut,
    TargetCreate,
)
from app.persistence.models import Evidence
from app.plugins.evidence import HeaderEvidenceData
from tests.header_evidence import header_evidence


@pytest.mark.parametrize("image", [None, "", "a" * 300, "a" * 301])
def test_target_image_input_respects_storage_limit(image):
    payload = {
        "project_id": "project",
        "name": "target",
        "image": image,
        "url": "http://demo-app:8080/",
    }
    if not image or len(image) > 300:
        with pytest.raises(ValidationError) as error:
            TargetCreate(**payload)
        assert error.value.errors()[0]["loc"] == ("image",)
    else:
        assert TargetCreate(**payload).image == image


@pytest.mark.parametrize(
    "selection",
    [{}, {"plugins": None}, {"plugins": []}, {"plugins": "http-security-headers"}],
)
def test_assessment_requires_explicit_nonempty_plugins(selection):
    with pytest.raises(ValidationError) as error:
        AssessmentCreate(
            project_id="project",
            target_id="target",
            url="http://demo-app:8080/",
            **selection,
        )
    assert error.value.errors()[0]["loc"] == ("plugins",)


def sized_url(length, *, normalized_growth=False):
    prefix = "https://example.test?" if normalized_growth else "https://example.test/"
    return prefix + "a" * (length - len(prefix))


@pytest.mark.parametrize(
    "schema,field,base",
    [
        (
            TargetCreate,
            "url",
            {"project_id": "p", "name": "target", "image": "demo:local"},
        ),
        (
            AssessmentCreate,
            "url",
            {"project_id": "p", "target_id": "t", "plugins": ["http-security-headers"]},
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
            assert error.value.errors()[0]["type"] == "too_long"


def test_assessment_rejects_unknown_fields():
    with pytest.raises(ValidationError) as error:
        AssessmentCreate(
            project_id="p",
            target_id="t",
            url="http://demo-app:8080/",
            plugins=["http-security-headers"],
            unexpected=True,
        )
    assert error.value.errors()[0]["type"] == "extra_forbidden"
    assert error.value.errors()[0]["loc"] == ("unexpected",)


@pytest.fixture(
    params=[
        {"header": "x-content-type-options"},
        {"header": "content-security-policy"},
        {"header": "x-frame-options"},
        {
            "header": "set-cookie",
            "cookie_name": "cross",
            "rule_id": "samesite-none-without-secure",
            "samesite": "none",
            "secure": False,
        },
        {
            "header": "set-cookie",
            "cookie_name": "__sEcUrE-session",
            "rule_id": "secure-prefix",
            "secure": True,
            "https": False,
        },
        {
            "header": "set-cookie",
            "cookie_name": "__hOsT-session",
            "rule_id": "host-prefix",
            "secure": True,
            "https": True,
            "domain_present": True,
            "root_path": False,
        },
    ]
)
def public_evidence(request):
    data = {"url": "https://example.test/app", **request.param}
    if data["header"] != "set-cookie":
        data = header_evidence(
            "framing-protection"
            if data["header"] == "x-frame-options"
            else data["header"],
            url=data["url"],
        )
    return {
        "id": "evidence-id",
        "finding_id": "finding-id",
        "kind": "http-response",
        "data": data,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"status_code": True},
        {"status_code": "200"},
        {"status_code": 600},
        {"rule_id": "arbitrary-rule"},
        {"condition": "raw-secret"},
        {"expected": "raw-secret"},
        {"media_type": "Text/HTML"},
        {"media_type": "text/html; raw-secret"},
        {"media_type": "raw-secret"},
    ],
)
def test_header_evidence_rejects_unvalidated_metadata(changes):
    data = {
        **header_evidence("x-content-type-options", url="https://example.test/"),
        **changes,
    }
    with pytest.raises(ValidationError) as error:
        EvidenceOut(id="e", finding_id="f", kind="http-response", data=data)
    assert "raw-secret" not in str(error.value)


@pytest.mark.parametrize(
    "rule,changes",
    [
        ("x-content-type-options", {"header": "content-security-policy"}),
        ("x-content-type-options", {"header": "x-frame-options"}),
        ("content-security-policy", {"header": "x-content-type-options"}),
        ("content-security-policy", {"header": "x-frame-options"}),
        ("framing-protection", {"header": "x-content-type-options"}),
        ("x-content-type-options", {"expected": "nonblank enforced CSP"}),
        (
            "content-security-policy",
            {"expected": "recognized restrictive framing protection"},
        ),
        ("framing-protection", {"expected": "nosniff"}),
        ("x-content-type-options", {"condition": "unrestricted"}),
        ("content-security-policy", {"condition": "unrestricted"}),
        ("framing-protection", {"condition": "unrestricted"}),
        (
            "framing-protection",
            {"header": "content-security-policy", "condition": "missing"},
        ),
        (
            "framing-protection",
            {"header": "content-security-policy", "condition": "blank"},
        ),
    ],
)
def test_header_evidence_rejects_contradictory_rule_metadata(rule, changes):
    with pytest.raises(ValidationError, match="contradicts its rule"):
        HeaderEvidenceData.model_validate({**header_evidence(rule), **changes})


@pytest.mark.parametrize(
    "media,accepted",
    [
        ("a" * 127 + "/" + "b" * 127, True),
        ("a" * 128 + "/b", False),
        ("a/" + "b" * 128, False),
        ("application/problem+json", True),
        ("text/html; charset=utf-8", False),
        ("TEXT/HTML", False),
        ("text/\u212a", False),
    ],
)
def test_public_media_type_limits_and_normalization(media, accepted):
    data = header_evidence(media_type=media)
    if accepted:
        assert HeaderEvidenceData.model_validate(data).media_type == media
    else:
        with pytest.raises(ValidationError):
            HeaderEvidenceData.model_validate(data)


@pytest.mark.parametrize("field", ["cookie_value", "raw_header", "unexpected"])
def test_public_evidence_rejects_extra_fields_without_echoing_values(
    public_evidence, field
):
    public_evidence["data"][field] = "synthetic-secret-not-for-output"
    with pytest.raises(ValidationError) as error:
        EvidenceOut(**public_evidence)
    assert "synthetic-secret-not-for-output" not in str(error.value)
    with pytest.raises(ValidationError) as error:
        EvidenceOut.model_validate(Evidence(**public_evidence), from_attributes=True)
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
            "rule_id": "host-prefix",
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
        {"rule_id": "unknown-rule"},
        {"samesite": "None"},
    ],
)
def test_public_cookie_evidence_rejects_invalid_values(changes):
    data = {
        "url": "https://example.test/",
        "header": "set-cookie",
        "cookie_name": "cross",
        "rule_id": "samesite-none-without-secure",
        "samesite": "none",
        "secure": False,
        **changes,
    }
    with pytest.raises(ValidationError):
        EvidenceOut(id="e", finding_id="f", kind="http-response", data=data)


@pytest.mark.parametrize("version", [None, 2, 3])
def test_report_requires_current_format(version):
    from app.api.schemas import AssessmentReportOut
    from tests.reports import report_fixture

    report = report_fixture()
    if version is None:
        report.pop("schema_version")
    else:
        report["schema_version"] = version
    with pytest.raises(ValidationError):
        AssessmentReportOut.model_validate(report)
