// Approval gating for SCR-13, mirroring WORKFLOW WF-06 and the server's checks (the server is the
// authority; this only makes the UI explain what is required before the request is sent).

import type { FixProposal, Role } from "./types";

export type CheckKey = "reviewed" | "unverified" | "breaking";

export interface Gate {
  applicable: CheckKey[];
  remaining: number;
  adminOverride: boolean;
  blocked: string | null;
  canApprove: boolean;
}

export function approvalGate(p: Pick<FixProposal, "status" | "validation" | "has_major_bump">, role: Role,
  checked: Record<CheckKey, boolean>, wideViewport: boolean, overrideComment = ""): Gate {
  const applicable: CheckKey[] = ["reviewed"];
  const result = p.validation.result;
  if (result === "unverified" || result === "not_run") applicable.push("unverified");
  if (p.has_major_bump) applicable.push("breaking");
  const remaining = applicable.filter((k) => !checked[k]).length;
  const adminOverride = result === "failed";
  let blocked: string | null = null;
  if (p.status !== "ready") blocked = `Only proposals in the ready state can be approved (this one is ${p.status.replace("_", " ")}).`;
  else if (role === "viewer") blocked = "Viewers cannot approve fix proposals.";
  else if (adminOverride && role !== "admin") blocked = "Tests failed after the change. Only an admin can override.";
  else if (!wideViewport) blocked = "Open on a desktop (≥ 768px) to approve.";
  else if (adminOverride && overrideComment.trim().length < 10) blocked = "An admin override needs a justification of at least 10 characters.";
  const canApprove = !blocked && remaining === 0;
  return { applicable, remaining, adminOverride, blocked, canApprove };
}
