"""Draft pull request creation and cleanup jobs (FR-REM-07, FR-REM-10, TH-19, TH-20).

* the job refuses to run unless the proposal is ``approved`` with a recorded approver;
* the branch is always ``toolkit/fix/<proposal-id>`` and is created as a new ref;
* the PR is a draft; nothing in the Toolkit can merge it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from toolkit import audit
from toolkit.core.errors import JobError, JobErrorCode
from toolkit.db.models import FixProposal, Job, Repository, ValidationRun
from toolkit.integrations.github import GitHubClient, GitHubError
from toolkit.jobs.queue import register_terminal_hook
from toolkit.jobs.runner import JobContext, register
from toolkit.services.credentials import load_token

GITHUB_FACTORY: Callable[[str | None], GitHubClient] = lambda token: GitHubClient(token, timeout=30.0)  # noqa: E731


def branch_for(proposal_id: uuid.UUID) -> str:
    return f"toolkit/fix/{proposal_id}"


def pr_body(p: FixProposal, runs: list[ValidationRun]) -> str:
    lines = [
        "Automated dependency fix proposed by the SRE + Code Health Toolkit.",
        "",
        "**This is a draft. Review and merge it on GitHub; the Toolkit never merges.**",
        "",
        "### Changes",
        "",
        "| Package | From | To | Bump | Files |",
        "|---|---|---|---|---|",
    ]
    for c in p.changes:
        lines.append(
            f"| `{c['package']}` ({c['ecosystem']}) | {c['from_version']} | {c['to_version']} | {c['bump']} "
            f"| `{c['manifest_path']}`, `{c['lockfile_path']}` |"
        )
    lines += ["", f"### Validation: `{p.validation_result}`", ""]
    for r in runs:
        if r.stage in ("baseline", "post_change"):
            lines.append(f"- {r.stage.replace('_', '-')} tests: {r.status} (exit {r.exit_code}, {r.duration_s:.0f} s)")
    delta = p.delta_scan or {}
    lines.append(
        f"- Delta scan: {len(delta.get('resolved_finding_ids', []))} targeted finding(s) resolved, "
        f"{len(delta.get('new_findings', []))} advisory match(es) on changed packages"
    )
    if p.risk_notes:
        lines += ["", "### Risk notes", ""] + [f"- {n}" for n in p.risk_notes]
    ack = p.approval_ack or {}
    lines += ["", "### Approval", "", f"- Approved at {p.approved_at.isoformat() if p.approved_at else 'n/a'}"]
    if ack.get("admin_override"):
        lines.append("- **Admin override:** tests failed after the change; justification recorded in the audit log.")
    if p.has_major_bump:
        lines.append("- Contains a **major version change** (acknowledged by the approver).")
    lines += [
        "",
        "### Rollback",
        "",
        f"Base commit: `{p.base_commit_sha}`. Before merge, close this PR. After merge, "
        "revert the merge commit with `git revert`.",
    ]
    return "\n".join(lines)[:60000]


@register("pr_creation")
def handle_pr_creation(ctx: JobContext) -> str:
    pid = uuid.UUID(ctx.payload["proposal_id"])
    with ctx.session() as db:
        p = db.get(FixProposal, pid, with_for_update=True)
        if p is None:
            raise JobError(JobErrorCode.INTERNAL_ERROR, "proposal missing")
        # Defence in depth: the approval row must exist before any remote write (SM-07).
        if p.status != "approved" or p.approved_by is None or p.approved_at is None:
            raise JobError(JobErrorCode.PR_PUSH_FAILED, "proposal is not approved")
        if not p.changed_files or not p.base_commit_sha:
            raise JobError(JobErrorCode.PR_PUSH_FAILED, "proposal has no validated change to push")
        repo = db.scalar(select(Repository).where(Repository.project_id == p.project_id))
        if repo is None:
            raise JobError(JobErrorCode.PR_PUSH_FAILED, "repository is no longer connected")
        token = load_token(db, repo.credential_id)
        runs = list(
            db.scalars(
                select(ValidationRun).where(ValidationRun.fix_proposal_id == pid).order_by(ValidationRun.started_at)
            )
        )
        body = pr_body(p, runs)
        files = dict(p.changed_files)
        title = (
            ("[major] " if p.has_major_bump else "")
            + "fix(deps): "
            + ", ".join(f"{c['package']} {c['to_version']}" for c in p.changes)[:200]
        )
        owner, name, base_sha = repo.owner, repo.name, p.base_commit_sha
        base_branch = p.base_ref or repo.default_branch
        db.expunge_all()
    if not token:
        raise JobError(JobErrorCode.PR_PUSH_FAILED, "a repository token with write access is required")
    branch = branch_for(pid)
    ctx.stage("push_branch")
    gh = GITHUB_FACTORY(token)
    try:
        gh.create_fix_branch_with_files(
            owner,
            name,
            branch=branch,
            base_sha=base_sha,
            files=files,
            message=title + "\n\nCreated by the SRE + Code Health Toolkit after approval.",
        )
        ctx.stage("open_draft_pr")
        pr = gh.open_draft_pr(owner, name, branch=branch, base=base_branch, title=title, body=body)
    except GitHubError as exc:
        hint = {
            "access_denied": "the token lacks Contents/Pull requests write permission",
            "invalid": "GitHub rejected the request (the branch may already exist)",
        }.get(exc.kind, str(exc))
        raise JobError(JobErrorCode.PR_PUSH_FAILED, hint[:300]) from exc
    finally:
        gh.close()
    with ctx.session() as db:
        p = db.get(FixProposal, pid, with_for_update=True)
        assert p is not None
        p.status = "pr_opened"
        p.pr_number, p.pr_url, p.pr_branch, p.pr_error = pr.number, pr.url, pr.branch, None
        audit.record(
            db,
            "fix.pr_opened",
            actor_id=p.approved_by,
            resource_type="fix_proposal",
            resource_id=p.id,
            metadata={"pr_number": pr.number, "branch": pr.branch},
        )
    return "succeeded"


def _pr_terminal(db: Session, job: Job, status: str) -> None:
    # GitHub failure: the proposal returns to approved with pr_error; no retry loop (WORKFLOW error paths).
    p = db.get(FixProposal, job.resource_id) if job.resource_id else None
    if p and p.status == "approved":
        p.pr_error = job.error_message or "PR creation failed"


register_terminal_hook("pr_creation", _pr_terminal)


@register("pr_cleanup")
def handle_pr_cleanup(ctx: JobContext) -> str:
    pid = uuid.UUID(ctx.payload["proposal_id"])
    with ctx.session() as db:
        p = db.get(FixProposal, pid)
        repo = db.scalar(select(Repository).where(Repository.project_id == p.project_id)) if p else None
        if p is None or repo is None or not p.pr_branch:
            raise JobError(JobErrorCode.PR_PUSH_FAILED, "nothing to clean up")
        token = load_token(db, repo.credential_id)
        owner, name, number, branch = repo.owner, repo.name, p.pr_number, p.pr_branch
    gh = GITHUB_FACTORY(token)
    try:
        if number:
            gh.close_pr(owner, name, number)
        gh.delete_fix_branch(owner, name, branch)  # refuses anything outside toolkit/fix/
    except GitHubError as exc:
        raise JobError(JobErrorCode.PR_PUSH_FAILED, str(exc)[:300]) from exc
    finally:
        gh.close()
    with ctx.session() as db:
        p = db.get(FixProposal, pid, with_for_update=True)
        assert p is not None
        p.pr_closed_at = ctx.clock.now()
        audit.record(
            db,
            "fix.branch_cleaned_up",
            actor_id=None,
            resource_type="fix_proposal",
            resource_id=p.id,
            metadata={"branch": branch},
        )
    return "succeeded"
