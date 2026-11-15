"""Bedrock Guardrail on the user's question (INPUT) and the final answer (OUTPUT), plus PII redaction for the trace.

See guardrails/01_bedrock_guardrail.md. The guardrail itself (denied topics, PII, content and prompt-attack filters)
is configured in the AWS console; this module only applies it with the Bedrock ApplyGuardrail API.

- configured(): (guardrail_id, version) from GUARDRAIL_ID / GUARDRAIL_VERSION, or None when GUARDRAIL_ID is unset
  or AGENT_MODE=demo (no LLM, no AWS calls). Then the pipeline skips the guardrail entirely.
- check(text, source): {"action": "NONE" | "GUARDRAIL_INTERVENED" | "ERROR", "source", "assessments", "error"?}.
  Never raises. An API error is reported as "ERROR" and the pipeline continues (fail open) with a trace note:
  the guardrail is a second line; persona-fit rules stay in the suitability worker.
- redact_pii(text): masks e-mails, phone numbers, Canadian SIN, card-like numbers and IBAN-like strings before
  text is written to the run trace (local JSON and S3). The models still get the original question.
"""
import os
import re

REGION = "us-east-1"
_client = None

# Order matters: longer / more specific patterns first so a card number is not half-eaten by the phone pattern.
PII_PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")),
    # "(?!\d|\.\d)": a sentence-ending period after the number is fine, a decimal part is not
    ("CARD", re.compile(r"(?<![\d.])\d(?:[ -]?\d){12,18}(?!\d|\.\d)")),  # 13-19 digits, spaces/dashes allowed
    ("SIN", re.compile(r"(?<![\d.])\d{3}[ -]\d{3}[ -]\d{3}(?!\d|\.\d)|(?<![\d.$,])\d{9}(?!\d|[.,]\d|%)")),
    ("PHONE", re.compile(r"(?<![\w.])(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d|\.\d)")),
]


def redact_pii(text):
    """Return text with PII replaced by [EMAIL], [IBAN], [CARD], [SIN] or [PHONE]. Non-strings are returned as is."""
    if not isinstance(text, str):
        return text
    for label, pattern in PII_PATTERNS:
        text = pattern.sub(f"[{label}]", text)
    return text


def configured():
    """(guardrail_id, version) or None when the guardrail is off (GUARDRAIL_ID unset, or AGENT_MODE=demo)."""
    gid = os.getenv("GUARDRAIL_ID", "").strip()
    if not gid or os.getenv("AGENT_MODE", "bedrock").strip().lower() == "demo":
        return None
    return gid, os.getenv("GUARDRAIL_VERSION", "DRAFT").strip() or "DRAFT"


def _bedrock():
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config
        _client = boto3.client("bedrock-runtime", region_name=REGION,
                               config=Config(retries={"max_attempts": 5, "mode": "adaptive"}))
    return _client


def _summary(assessments) -> list[dict]:
    """Which policies fired (names/types/actions only, never the matched text)."""
    out = []
    for a in assessments or []:
        for policy, body in a.items():
            if not isinstance(body, dict):
                continue
            for key, items in body.items():
                if isinstance(items, list):
                    for it in items:
                        if isinstance(it, dict):
                            out.append({"policy": policy, "kind": key,
                                        "name": it.get("name") or it.get("type"), "action": it.get("action")})
    return out


def check(text: str, source: str) -> dict:
    """Apply the configured guardrail to `text` (source "INPUT" or "OUTPUT"). Never raises."""
    cfg = configured()
    if cfg is None:
        return {"action": "SKIPPED", "source": source, "assessments": []}
    try:
        r = _bedrock().apply_guardrail(guardrailIdentifier=cfg[0], guardrailVersion=cfg[1], source=source,
                                       content=[{"text": {"text": text}}])
        return {"action": r.get("action", "NONE"), "source": source,
                "assessments": _summary(r.get("assessments")), "guardrail": {"id": cfg[0], "version": cfg[1]}}
    except Exception as e:
        return {"action": "ERROR", "source": source, "assessments": [], "error": redact_pii(str(e))[:300]}
