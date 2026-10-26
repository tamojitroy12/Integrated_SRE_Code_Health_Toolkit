"""Operator CLI: ``python -m toolkit.cli <command>`` (or the ``toolkit`` script)."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from toolkit.core.config import get_settings


def cmd_migrate(_args: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.attributes["url"] = get_settings().database_url
    command.upgrade(cfg, "head")
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    from toolkit.core.security import hash_password
    from toolkit.db.models import User
    from toolkit.db.session import session_scope
    from toolkit.services.auth import find_user_by_email, normalize_email

    password = args.password or getpass.getpass("Password (12-128 chars): ")
    if not 12 <= len(password) <= 128:
        print("password must be 12-128 characters", file=sys.stderr)
        return 2
    with session_scope() as db:
        if find_user_by_email(db, args.email):
            print("user already exists", file=sys.stderr)
            return 1
        db.add(
            User(
                email=normalize_email(args.email),
                display_name=args.name or args.email.split("@")[0],
                role=args.role,
                password_hash=hash_password(password),
                is_active=True,
            )
        )
    print(f"created {args.role} {args.email}")
    return 0


def cmd_seed_demo(args: argparse.Namespace) -> int:
    """FR-PRJ-06: a demo project linked to examples/ (demo-app target + default rules)."""
    from toolkit.api.routes.targets import DEFAULT_RULES
    from toolkit.db.models import AlertRule, MonitoringTarget, Project, Repository
    from toolkit.db.session import session_scope

    with session_scope() as db:
        project = db.scalar(select(Project).where(Project.name == args.name, Project.archived_at.is_(None)))
        if project is None:
            project = Project(name=args.name, description="Demo project seeded from examples/ (FR-PRJ-06).")
            db.add(project)
            db.flush()
        target = db.scalar(
            select(MonitoringTarget).where(
                MonitoringTarget.project_id == project.id, MonitoringTarget.service_name == "demo-app"
            )
        )
        if target is None:
            target = MonitoringTarget(
                project_id=project.id,
                name="Demo app",
                service_name="demo-app",
                environment="dev",
                ingestion_mode="otlp_push",
                status="waiting",
            )
            db.add(target)
            db.flush()
            for spec in DEFAULT_RULES:
                db.add(
                    AlertRule(
                        project_id=project.id, target_id=target.id, resolve_after=3, params={}, enabled=True, **spec
                    )
                )
        if args.repo:
            from toolkit.core.validators import parse_github_url

            parsed = parse_github_url(args.repo)
            if parsed is None:
                print("--repo must be https://github.com/<owner>/<name>", file=sys.stderr)
                return 2
            if db.scalar(select(Repository).where(Repository.project_id == project.id)) is None:
                db.add(
                    Repository(
                        project_id=project.id,
                        owner=parsed[0],
                        name=parsed[1],
                        url=f"https://github.com/{parsed[0]}/{parsed[1]}",
                        default_branch=args.branch,
                        ecosystems=["npm", "pypi"],
                        manifests=[],
                        can_open_prs=False,
                    )
                )
        print(json.dumps({"project_id": str(project.id), "target_id": str(target.id)}))
    return 0


def cmd_hard_delete(args: argparse.Namespace) -> int:
    from toolkit.db.models import Project
    from toolkit.db.session import session_scope

    with session_scope() as db:
        project = db.get(Project, uuid.UUID(args.project_id))
        if project is None:
            print("project not found", file=sys.stderr)
            return 1
        if project.archived_at is None and not args.force:
            print("project is not archived; archive it first or pass --force", file=sys.stderr)
            return 1
        db.delete(project)  # cascades to every dependent row
    print("deleted")
    return 0


def cmd_retention(_args: argparse.Namespace) -> int:
    from toolkit.core.clock import utcnow
    from toolkit.db.session import session_scope
    from toolkit.retention import run_retention

    with session_scope() as db:
        print(json.dumps(run_retention(db, utcnow())))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="toolkit")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(fn=cmd_migrate)
    p = sub.add_parser("create-user", help="create a user")
    p.add_argument("email")
    p.add_argument("--role", choices=["viewer", "maintainer", "admin"], default="viewer")
    p.add_argument("--name")
    p.add_argument("--password")
    p.set_defaults(fn=cmd_create_user)
    p = sub.add_parser("seed-demo", help="seed a demo project (FR-PRJ-06)")
    p.add_argument("--name", default="demo")
    p.add_argument("--repo", help="GitHub URL of a repository to connect, e.g. a fork of examples/vulnerable-repo")
    p.add_argument("--branch", default="main")
    p.set_defaults(fn=cmd_seed_demo)
    p = sub.add_parser("hard-delete-project", help="permanently delete an archived project")
    p.add_argument("project_id")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_hard_delete)
    sub.add_parser("retention", help="apply retention now").set_defaults(fn=cmd_retention)
    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
