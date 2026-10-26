"""Project lookup helpers with object-level access checks (SECURITY §6)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from toolkit.core.errors import ApiError, ErrorCode, not_found
from toolkit.db.models import Project


def get_project(db: Session, project_id: uuid.UUID, *, writable: bool = False, lock: bool = False) -> Project:
    project = db.get(Project, project_id, with_for_update=lock)
    if project is None:
        raise not_found("Project")
    if writable and project.archived_at is not None:
        raise ApiError(ErrorCode.CONFLICT, "Project is archived and read-only.")
    return project
