"""Shared persistence limits and validation types."""

from typing import Annotated

from pydantic import AfterValidator, AnyHttpUrl, Field, UrlConstraints

NAME_MAX_LENGTH = 200
TARGET_IMAGE_MAX_LENGTH = 300
MAX_ASSESSMENT_ATTEMPTS = 2
PLUGIN_ID_MAX_LENGTH = 100
FINDING_TITLE_MAX_LENGTH = 300
FINDING_SEVERITY_MAX_LENGTH = 30
STORED_URL_MAX_LENGTH = 500

TargetImage = Annotated[str, Field(max_length=TARGET_IMAGE_MAX_LENGTH)]


def _require_storable_url(value: AnyHttpUrl) -> AnyHttpUrl:
    if len(str(value)) > STORED_URL_MAX_LENGTH:
        raise ValueError(
            f"normalized URL must contain at most {STORED_URL_MAX_LENGTH} characters"
        )
    return value


StoredHttpUrl = Annotated[
    AnyHttpUrl,
    UrlConstraints(max_length=STORED_URL_MAX_LENGTH),
    AfterValidator(_require_storable_url),
]
