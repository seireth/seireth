import pytest
from pydantic import ValidationError

from app.schemas import AssessmentCreate, ScopeCreate, TargetCreate


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


def test_persisted_urls_are_bounded_after_normalization():
    exact = sized_url(500)
    assert len(str(TargetCreate(project_id="p", name="target", url=exact).url)) == 500
    assert (
        len(
            str(
                ScopeCreate(
                    project_id="p",
                    target_id="t",
                    allowed_url=exact,
                    expires_at="2099-01-01T00:00:00Z",
                ).allowed_url
            )
        )
        == 500
    )
    with pytest.raises(ValidationError, match="normalized URL"):
        TargetCreate(
            project_id="p",
            name="target",
            url=sized_url(500, normalized_growth=True),
        )
    with pytest.raises(ValidationError):
        ScopeCreate(
            project_id="p",
            target_id="t",
            allowed_url=sized_url(501),
            expires_at="2099-01-01T00:00:00Z",
        )
