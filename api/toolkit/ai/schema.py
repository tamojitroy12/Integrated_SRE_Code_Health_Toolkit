"""Model output schema (AI_DESIGN §5.1, API_SPEC §5.8).

The JSON schema is sent to the model as a structured-output format; the Pydantic models
re-validate the result so nothing unvalidated reaches the validator or the database.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CHECKABLE_CLAIMS = {
    "fixed_version",
    "version_exists",
    "deprecation",
    "alternative_exists",
    "alternative_property",
    "code_location",
    "patch_applies",
}
JUDGMENT_CLAIMS = {"compatibility", "effort", "risk", "code_quality"}
ClaimType = Literal[
    "fixed_version",
    "version_exists",
    "deprecation",
    "alternative_exists",
    "alternative_property",
    "code_location",
    "patch_applies",
    "compatibility",
    "effort",
    "risk",
    "code_quality",
]


class ClaimSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package: str | None = None
    ecosystem: Literal["npm", "pypi"] | None = None
    version: str | None = None
    property: Literal["license", "latest_version", "deprecated", "repository_url"] | None = None
    value: str | None = None
    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str = Field(max_length=20)
    type: ClaimType
    text: str = Field(max_length=600)
    evidence_refs: list[str] = Field(max_length=10)
    subject: ClaimSubject | None = None


class Alternative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=214)
    ecosystem: Literal["npm", "pypi"]
    rationale: str = Field(max_length=600)
    evidence_refs: list[str] = Field(max_length=10)


class ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=600)
    claims: list[Claim] = Field(max_length=15)
    alternatives: list[Alternative] = Field(max_length=5)
    suggested_steps: list[str] = Field(max_length=10)
    proposed_patch: str | None = Field(default=None, max_length=8000)
    confidence: Literal["low", "medium", "high"]
    limitations: list[str] = Field(min_length=1, max_length=10)

    @field_validator("suggested_steps", "limitations")
    @classmethod
    def _bounded(cls, v: list[str]) -> list[str]:
        return [s[:400] for s in v]


def _nullable(t: str, **extra: Any) -> dict[str, Any]:
    return {"type": [t, "null"], **extra}


SUBJECT_SCHEMA: dict[str, Any] = {
    "type": ["object", "null"],
    "additionalProperties": False,
    "properties": {
        "package": _nullable("string"),
        "ecosystem": {"type": ["string", "null"], "enum": ["npm", "pypi", None]},
        "version": _nullable("string"),
        "property": {
            "type": ["string", "null"],
            "enum": ["license", "latest_version", "deprecated", "repository_url", None],
        },
        "value": _nullable("string"),
        "file": _nullable("string"),
        "line_start": _nullable("integer"),
        "line_end": _nullable("integer"),
    },
    "required": ["package", "ecosystem", "version", "property", "value", "file", "line_start", "line_end"],
}

OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "claim_id": {"type": "string"},
                    "type": {"type": "string", "enum": sorted(CHECKABLE_CLAIMS | JUDGMENT_CLAIMS)},
                    "text": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "subject": SUBJECT_SCHEMA,
                },
                "required": ["claim_id", "type", "text", "evidence_refs", "subject"],
            },
        },
        "alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "ecosystem": {"type": "string", "enum": ["npm", "pypi"]},
                    "rationale": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "ecosystem", "rationale", "evidence_refs"],
            },
        },
        "suggested_steps": {"type": "array", "items": {"type": "string"}},
        "proposed_patch": {"type": ["string", "null"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "claims", "alternatives", "suggested_steps", "proposed_patch", "confidence", "limitations"],
}
