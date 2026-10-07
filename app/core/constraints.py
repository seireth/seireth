"""Shared persistence limits and validation types."""

from typing import Annotated

from pydantic import AnyHttpUrl, Field, UrlConstraints

NAME_MAX_LENGTH = 200
TARGET_IMAGE_MAX_LENGTH = 300
MAX_ASSESSMENT_ATTEMPTS = 2
PLUGIN_ID_MAX_LENGTH = 100
FINDING_TITLE_MAX_LENGTH = 300
FINDING_SEVERITY_MAX_LENGTH = 30
STORED_URL_MAX_LENGTH = 500
TARGET_IMAGE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]*$"
MEDIA_TYPE_PART_MAX_LENGTH = 127
MEDIA_TYPE_MAX_LENGTH = MEDIA_TYPE_PART_MAX_LENGTH * 2 + 1
_MEDIA_TYPE_PART = rf"[a-z0-9][a-z0-9!#$&^_.+-]{{0,{MEDIA_TYPE_PART_MAX_LENGTH - 1}}}"
MEDIA_TYPE_PATTERN = rf"{_MEDIA_TYPE_PART}/{_MEDIA_TYPE_PART}"

NormalizedMediaType = Annotated[
    str, Field(max_length=MEDIA_TYPE_MAX_LENGTH, pattern=rf"^{MEDIA_TYPE_PATTERN}$")
]

TargetImage = Annotated[
    str,
    Field(
        min_length=1,
        max_length=TARGET_IMAGE_MAX_LENGTH,
        pattern=TARGET_IMAGE_PATTERN,
    ),
]

StoredHttpUrl = Annotated[
    AnyHttpUrl,
    UrlConstraints(max_length=STORED_URL_MAX_LENGTH),
    Field(max_length=STORED_URL_MAX_LENGTH),
]
