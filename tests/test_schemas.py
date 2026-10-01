import pytest
from pydantic import ValidationError

from app.schemas import AssessmentCreate, ProjectCreate, ScopeCreate, TargetCreate


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
