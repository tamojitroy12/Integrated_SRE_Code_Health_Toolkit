# Glossary

> **Doc:** GLOSSARY.md · **Version:** 0.2 · **Date:** 2026-10-13 · **Status:** Draft · **Related:** all documents

Terms are used with exactly these meanings throughout the documentation. Identifiers (`FR-*`, `COMP-*`, etc.) are listed in [SRS §2](SRS.md#2-identifier-scheme). Labels **[V]**, **[P]**, **[A]**, **[U]** are defined in the [README](../README.md#documentation-conventions).

## Domain terms

| Term | Definition | See |
|---|---|---|
| **Acknowledgment gate** | A required confirmation (checkbox/API flag) before approving a fix proposal whose validation is `unverified` or that includes a major version bump. | WF-06, FR-REM-09, FR-REM-12 |
| **Advisory** | A published record describing a vulnerability and the affected and fixed versions of a package (for example from OSV). | DATA_MODEL §2.5 |
| **AI Advisor** | COMP-07; builds evidence packs, calls the LLM, validates output, and stores recommendations. | ARCHITECTURE §3 |
| **Alert** | A record that an alert rule's condition held for the required duration; lifecycle `firing → acknowledged → resolved`. | WF-03 |
| **Alert rule** | A configured condition on a metric of a monitoring target: `threshold`, `anomaly`, or `absence`. | API_SPEC §5.5 |
| **Alias set** | The set of identifiers (CVE, GHSA, OSV ID, …) that refer to the same advisory; used to merge duplicate findings. | FR-DEP-04 |
| **Anomaly (z-score)** | A statistical deviation of a metric from its recent baseline, flagged when \( \lvert z_t \rvert > k \) for \( N \) consecutive evaluations. | TRD §6.2 |
| **Approval** | A recorded decision by a `maintainer` or `admin` that allows PR creation for a fix proposal. Required before any remote write. | DEC-011 |
| **Baseline test** | The repository's test command run before a change is applied, to know whether tests were passing already. | FR-REM-04 |
| **Claim** | One statement in an AI recommendation, with a type and evidence references; checkable or judgment. | AI_DESIGN §5.1 |
| **Collector** | The OpenTelemetry Collector (COMP-12) that receives OTLP, checks the ingest token, and forwards metrics. | TRD §3 |
| **Confidence** | The model's qualitative statement (`low/medium/high`), capped by validation status; not a probability. | AI_DESIGN §6.1 |
| **Dependency (direct/transitive)** | A package required by the project; direct if declared by the project, transitive if pulled in by another dependency. | DATA_MODEL §2.5 |
| **Detection time** | \( T_{detect} \): time from fault onset to alert creation; bounded by \( T_{ingest} + N \cdot \Delta_{eval} \). | TRD §6.2 |
| **Draft PR** | A GitHub pull request opened as a draft by the Toolkit; merging is always done by humans. | FR-REM-07 |
| **Evaluation interval** | \( \Delta_{eval} \), the period at which alert rules are evaluated (`ALERT_EVAL_INTERVAL_SECONDS`). | README |
| **Evidence** | An immutable, sourced fact attached to a finding or alert (advisory record, registry metadata, snippet, scanner output, metric evaluation). | DATA_MODEL §2.5 |
| **Evidence pack** | The hashed, bounded, redacted bundle of evidence items (with IDs `ev-n`) sent to the LLM. | AI_DESIGN §4 |
| **Finding** | A normalized issue discovered by a scan: `dependency_vulnerability`, `dependency_outdated`, `dependency_incompatibility`, or `code_issue`. | DATA_MODEL §2.5 |
| **Fingerprint** | A stable hash identifying a finding across scans (excludes line numbers). | TRD §5.2 |
| **Fix proposal** | A deterministic, sandbox-validated plan and diff to update dependencies; becomes a draft PR only after approval. | WF-06 |
| **Grounding** | Constraining AI output to stored, verifiable evidence and verifying checkable claims mechanically. | AI_DESIGN §3 |
| **Heuristic** | A rule-based indicator that suggests but does not prove a condition (for example potential incompatibility from a major version bump). | FR-DEP-06 |
| **Hallucination (unsupported claim)** | A claim in model output not supported by the evidence pack or failing a mechanical check. | AI_DESIGN §6 |
| **Ingest token** | The shared bearer token monitored applications present to the Collector. | DEC-014 |
| **Job** | A durable, leased unit of asynchronous work (`scan`, `recommendation`, `fix_proposal`, `pr_creation`). | WORKFLOW (job lifecycle) |
| **Lease** | A time-limited claim on a job by a worker; expiry causes requeue. | NFR-REL-01 |
| **Lockfile** | A file pinning exact resolved dependency versions (for example `package-lock.json`). | FR-REM-03 |
| **Monitoring Engine** | COMP-04; periodic evaluation of alert rules against Prometheus. | ARCHITECTURE §3 |
| **Monitoring target** | A running service registered in a project, identified by `service_name` and `environment`. | DATA_MODEL §2.2 |
| **Observability data** | Here: OpenTelemetry **metrics** only in the MVP. Traces and logs are out of scope. | CON-03 |
| **OSV** | The Open Source Vulnerabilities database and API used for advisory matching and records. | TRD §5.1 **[V]** |
| **OTLP** | The OpenTelemetry Protocol used to send telemetry (HTTP and gRPC). | SRS IF-01 |
| **Partial scan** | A scan in which at least one provider failed; never presented as a clean result. | FR-DEP-07 |
| **Project** | The unifying entity linking an optional repository and optional monitoring targets, with their alerts, scans, and findings. | ARCHITECTURE §7 |
| **Prometheus / PromQL** | The time-series database and its query language used for runtime metrics. | TRD §4 |
| **Provider (scan provider)** | A data source or tool used in a scan: `trivy`, `osv`, `registry`, `semgrep`. | DATA_MODEL §2.5 |
| **Recommendation** | A stored, validated AI output about one finding (`library_alternative`, `upgrade_guidance`, `code_improvement`). | API_SPEC §5.8 |
| **Registry** | A package index (npm, PyPI) used for metadata and existence checks. | IF-04 |
| **Remediation Engine** | COMP-09; builds change plans, orchestrates the sandbox, and creates PRs after approval. | ARCHITECTURE §3 |
| **Sandbox** | The isolated container runtime (COMP-14) where repository code and dependency installation run. | SECURITY §9 |
| **Scan** | One analysis of a repository at a specific commit by one or more providers. | DATA_MODEL §2.5 |
| **Semgrep** | The static-analysis engine used for code-issue findings. | DEC-007 |
| **Severity** | `critical`, `high`, `medium`, `low`, `info`, or `null` (unrated). Never invented when the source gives none. | TRD §5.3 |
| **SLI (availability)** | \( \text{SLI}_{avail,W} = 1 - R_{5xx}/R_{total} \) over a window; undefined without traffic. | TRD §6.1 |
| **Stale target** | A monitoring target with no samples for longer than `TARGET_STALE_AFTER_SECONDS` (\( \Delta > \text{TARGET\_STALE\_AFTER\_SECONDS} \); receiving when \( \Delta \le \text{TARGET\_STALE\_AFTER\_SECONDS} \)). | FR-PRJ-04 |
| **Static analysis** | Examining source code without running it; cannot establish runtime health. | ARCHITECTURE §3.2 |
| **Trivy** | The scanner used for dependency inventory and vulnerability matching (vulnerability scanner only; secret scanning not enabled). | DEC-006 |
| **Trust boundary** | A line between components with different trust levels (TB-1…TB-6). | SECURITY §3 |
| **Unverified (validation result)** | A fix proposal whose baseline tests were missing or failing, so passing post-change tests prove little. | FR-REM-12 |
| **Validation result** | Outcome of a fix proposal's sandbox checks: `passed`, `failed`, `unverified`, `not_run`. | DATA_MODEL §3 |
| **Validation status** | Outcome of the AI validator: `validated`, `partially_validated`, `rejected`. | AI_DESIGN §6.1 |
| **Validator** | Code that checks schema, evidence references, package and version existence, advisory consistency, and patch applicability for AI output. | AI_DESIGN §6 |

## Acronyms

| Acronym | Meaning |
|---|---|
| API | Application Programming Interface |
| CSRF | Cross-Site Request Forgery |
| CVE / GHSA | Common Vulnerabilities and Exposures / GitHub Security Advisory identifiers |
| LLM | Large language model |
| PAT | Personal access token (GitHub) |
| PR | Pull request |
| RBAC | Role-based access control |
| SBOM | Software bill of materials |
| SRE | Site reliability engineering |
| SSRF | Server-side request forgery |
| STRIDE | Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege |
| UC / US | Use case / user story |
