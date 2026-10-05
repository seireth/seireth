"""Shared HTTP authorization, pagination, and browser write checks."""

from urllib.parse import urlsplit

from fastapi import HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..assessments.policy import ACTOR, http_origin
from ..persistence import models


def authorize_project(db: Session, project_id: str) -> models.Project:
    project = db.get(models.Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    if project.owner_actor != ACTOR:
        raise HTTPException(403, "project access denied")
    return project


def pagination(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return offset, limit


def page(db: Session, query, bounds: tuple[int, int]):
    offset, limit = bounds
    rows = db.scalars(query.offset(offset).limit(limit + 1)).all()
    return {"items": rows[:limit], "has_more": len(rows) > limit}


def browser_origin(request: Request):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin is None:
        return
    try:
        supplied = urlsplit(origin)
        actual = urlsplit(str(request.url))

        if (
            supplied.scheme in {"http", "https"}
            and not any(character.isspace() for character in origin)
            and supplied.hostname
            and supplied.username is None
            and supplied.password is None
            and not supplied.path
            and not supplied.query
            and not supplied.fragment
            and http_origin(supplied) == http_origin(actual)
        ):
            return
    except ValueError:
        pass
    raise HTTPException(403, "browser origin is not allowed")
