"""Deterministic safety gates used before an agent can receive work.

This module deliberately makes no outbound calls.  It is the policy boundary that
the future LLM gateway (M3) must call immediately before it sends any content to
a provider.
"""

from dataclasses import dataclass
import re


LOCAL_PROVIDER_NAMES = {"local", "ollama", "vllm", "llama_cpp", "llamacpp"}

# These are intentionally conservative.  A match means "hold for a safer path",
# not that the value is conclusively a patient identifier.
PATIENT_IDENTIFIER_PATTERNS = (
    re.compile(r'(?i)\b(?:patient[_ -]?id|mrn|medical[_ -]?record(?:[_ -]?number)?|national[_ -]?id|nhis[_ -]?id)\b["\']?\s*[:=]'),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?<!\d)(?:\+?855|0)\d{8,10}(?!\d)"),
)

HIGH_IMPACT_TASK_PATTERN = re.compile(
    r"(?i)(clinical|triage|diagnos|prescri|medication|drug|referral|treatment|"
    r"care[_ -]?plan|patient[_ -]?record|discharge|order|appointment[_ -]?change|"
    r"publish|send|delete|payment|financial|access[_ -]?grant)"
)


@dataclass(frozen=True)
class SafetyDecision:
    contains_patient_identifiers: bool
    requires_human_approval: bool
    reason: str | None


def is_external_provider(provider: str) -> bool:
    return provider.strip().lower() not in LOCAL_PROVIDER_NAMES


def has_potential_patient_identifier(*values: str | None) -> bool:
    text = "\n".join(value for value in values if value)
    return any(pattern.search(text) for pattern in PATIENT_IDENTIFIER_PATTERNS)


def evaluate_execution_safety(
    *,
    model_provider: str,
    task_type: str,
    input_payload: str | None,
    task_payload: str | None,
) -> SafetyDecision:
    contains_identifiers = has_potential_patient_identifier(input_payload, task_payload)
    if contains_identifiers and is_external_provider(model_provider):
        raise ValueError(
            "External LLM execution is denied because the request may contain patient-identifying data. "
            "Use an approved local/de-identified workflow; an external provider requires an authorized "
            "data-processing arrangement and an explicit gateway policy, neither of which is enabled."
        )

    requires_approval = bool(HIGH_IMPACT_TASK_PATTERN.search(task_type))
    return SafetyDecision(
        contains_patient_identifiers=contains_identifiers,
        requires_human_approval=requires_approval,
        reason="high_impact_action" if requires_approval else None,
    )
