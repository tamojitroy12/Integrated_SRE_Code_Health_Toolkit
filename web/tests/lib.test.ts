import { describe, expect, it } from "vitest";

import { approvalGate } from "@/lib/approval";
import { formatDuration, formatMetric, sentence, shortSha, timeAgo } from "@/lib/format";
import { describeSeconds, normalizeRepo, parseDuration, parseLatency, parseRatio, sanitize } from "@/lib/parse";
import type { FixProposal } from "@/lib/types";

describe("normalizeRepo (Postel's law)", () => {
  it.each([
    ["org/repo", "https://github.com/org/repo"],
    ["github.com/org/repo", "https://github.com/org/repo"],
    ["https://github.com/org/repo.git", "https://github.com/org/repo"],
    ["https://github.com/org/repo/tree/main/src", "https://github.com/org/repo"],
    ["git@github.com:org/repo.git", "https://github.com/org/repo"],
    ["  https://www.github.com/org/repo/  \n", "https://github.com/org/repo"],
  ])("%s", (input, url) => {
    expect(normalizeRepo(input)?.url).toBe(url);
  });
  it("rejects other hosts and garbage", () => {
    expect(normalizeRepo("https://gitlab.com/org/repo")).toBeNull();
    expect(normalizeRepo("just-a-word")).toBeNull();
    expect(normalizeRepo("org/re po")).toBeNull();
  });
});

describe("duration, ratio and latency parsing", () => {
  it("parses durations to seconds", () => {
    expect(parseDuration("5m")).toBe(300);
    expect(parseDuration("300s")).toBe(300);
    expect(parseDuration("1h30m")).toBe(5400);
    expect(parseDuration("90")).toBe(90);
    expect(parseDuration("5 minutes")).toBeNull();
    expect(describeSeconds(300)).toBe("5 minutes (300 s)");
  });
  it("parses ratios and flags ambiguous integers", () => {
    expect(parseRatio("5%")).toEqual({ value: 0.05 });
    expect(parseRatio("0.05")).toEqual({ value: 0.05 });
    expect(parseRatio("5")).toEqual({ ambiguous: 0.05 });
    expect(parseRatio("500")).toBeNull();
  });
  it("parses latency", () => {
    expect(parseLatency("250ms")).toBe(0.25);
    expect(parseLatency("2s")).toBe(2);
    expect(parseLatency("1.5")).toBe(1.5);
    expect(parseLatency("fast")).toBeNull();
  });
  it("sanitizes pasted values", () => {
    expect(sanitize(" tok​en \r\n")).toBe("token");
  });
});

describe("formatting", () => {
  it("formats metrics without inventing values", () => {
    expect(formatMetric(0.0523, "ratio")).toBe("5.23%");
    expect(formatMetric(0.12, "seconds")).toBe("120 ms");
    expect(formatMetric(4.2, "requests_per_second")).toBe("4.20 req/s");
    expect(formatMetric(null, "ratio")).toBe("—");
    expect(formatDuration(90)).toBe("1 min 30 s");
    expect(shortSha("a".repeat(40))).toBe("aaaaaaa");
    expect(sentence("partially_validated")).toBe("Partially validated");
    expect(timeAgo(new Date(1000_000).toISOString(), 1000_000 + 120_000)).toBe("2m ago");
  });
});

function proposal(result: FixProposal["validation"]["result"], major = false, status: FixProposal["status"] = "ready") {
  return { status, validation: { result }, has_major_bump: major };
}
const none = { reviewed: false, unverified: false, breaking: false };
const all = { reviewed: true, unverified: true, breaking: true };

describe("approval gate (WF-06 matrix)", () => {
  it("passed: maintainer needs only the review checkbox", () => {
    const g = approvalGate(proposal("passed"), "maintainer", none, true);
    expect(g.applicable).toEqual(["reviewed"]);
    expect(g.remaining).toBe(1);
    expect(g.canApprove).toBe(false);
    expect(approvalGate(proposal("passed"), "maintainer", { ...none, reviewed: true }, true).canApprove).toBe(true);
  });
  it("major bump requires the breaking-change acknowledgment", () => {
    const g = approvalGate(proposal("passed", true), "maintainer", { ...none, reviewed: true }, true);
    expect(g.applicable).toContain("breaking");
    expect(g.canApprove).toBe(false);
  });
  it("unverified requires the unverified acknowledgment", () => {
    expect(approvalGate(proposal("unverified"), "maintainer", { ...none, reviewed: true }, true).remaining).toBe(1);
    expect(approvalGate(proposal("unverified"), "maintainer", all, true).canApprove).toBe(true);
  });
  it("failed: admin only, with a justification", () => {
    expect(approvalGate(proposal("failed"), "maintainer", all, true).blocked).toMatch(/Only an admin/);
    expect(approvalGate(proposal("failed"), "admin", all, true, "short").canApprove).toBe(false);
    expect(approvalGate(proposal("failed"), "admin", all, true, "Known flaky test, verified").canApprove).toBe(true);
  });
  it("narrow viewports and non-ready states cannot approve", () => {
    expect(approvalGate(proposal("passed"), "admin", all, false).blocked).toBe("Open on a desktop (≥ 768px) to approve.");
    expect(approvalGate(proposal("passed", false, "pr_opened"), "admin", all, true).canApprove).toBe(false);
    expect(approvalGate(proposal("passed"), "viewer", all, true).canApprove).toBe(false);
  });
});
