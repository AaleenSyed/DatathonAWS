"""guardrail.py: PII redaction and the Bedrock Guardrail switch (no AWS calls)."""
import pytest

import guardrail


@pytest.mark.parametrize("raw,label", [
    ("write to jane.doe+fin@example.co.uk please", "[EMAIL]"),
    ("call me at (514) 555-0199", "[PHONE]"),
    ("call me at +1 514-555-0199", "[PHONE]"),
    ("my SIN is 046 454 286", "[SIN]"),
    ("my SIN is 046-454-286", "[SIN]"),
    ("my SIN is 046454286", "[SIN]"),
    ("card 4111 1111 1111 1111 exp 12/27", "[CARD]"),
    ("card 4111-1111-1111-1111", "[CARD]"),
    ("IBAN GB82 WEST 1234 5698 7654 32", "[IBAN]"),
])
def test_pii_is_redacted(raw, label):
    out = guardrail.redact_pii(raw)
    assert label in out
    digits = [c for c in raw if c.isdigit()]
    assert "".join(digits[-4:]) not in out.replace(" ", "").replace("-", "") or label == "[EMAIL]"


@pytest.mark.parametrize("text", [
    "I want to put a big part of my savings in NVDA, good idea?",
    "Is 15% crypto too much for Amira? Vol was 51.1% in 2022 (2021-11-12 to 2026-11-12).",
    "Robert has $50,000 and a 3-5 year horizon; XBB.TO fell 12.3% in 2022.",
    "Which industry gives balanced growth for me? 10-year view, 1,254 days of data.",
])
def test_finance_text_is_unchanged(text):
    assert guardrail.redact_pii(text) == text


def test_non_strings_pass_through():
    assert guardrail.redact_pii(None) is None and guardrail.redact_pii(5) == 5


def test_off_without_id_or_in_demo_mode(monkeypatch):
    monkeypatch.delenv("GUARDRAIL_ID", raising=False)
    assert guardrail.configured() is None
    assert guardrail.check("hello", "INPUT")["action"] == "SKIPPED"
    monkeypatch.setenv("GUARDRAIL_ID", "gr-123")
    monkeypatch.setenv("AGENT_MODE", "demo")
    assert guardrail.configured() is None
    monkeypatch.setenv("AGENT_MODE", "bedrock")
    monkeypatch.delenv("GUARDRAIL_VERSION", raising=False)
    assert guardrail.configured() == ("gr-123", "DRAFT")


class FakeBedrock:
    def __init__(self, action="GUARDRAIL_INTERVENED", fail=False):
        self.calls, self.action, self.fail = [], action, fail

    def apply_guardrail(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("AccessDenied for jane@example.com")
        return {"action": self.action, "assessments": [
            {"topicPolicy": {"topics": [{"name": "PersonalAdvice", "type": "DENY", "action": "BLOCKED"}]}}]}


def test_check_calls_apply_guardrail(monkeypatch):
    monkeypatch.setenv("GUARDRAIL_ID", "gr-123")
    monkeypatch.setenv("GUARDRAIL_VERSION", "2")
    monkeypatch.setenv("AGENT_MODE", "bedrock")
    fake = FakeBedrock()
    monkeypatch.setattr(guardrail, "_bedrock", lambda: fake)
    r = guardrail.check("buy NVDA for me", "INPUT")
    assert fake.calls == [{"guardrailIdentifier": "gr-123", "guardrailVersion": "2", "source": "INPUT",
                           "content": [{"text": {"text": "buy NVDA for me"}}]}]
    assert r["action"] == "GUARDRAIL_INTERVENED"
    assert r["assessments"] == [{"policy": "topicPolicy", "kind": "topics", "name": "PersonalAdvice",
                                 "action": "BLOCKED"}]


def test_check_never_raises_and_redacts_errors(monkeypatch):
    monkeypatch.setenv("GUARDRAIL_ID", "gr-123")
    monkeypatch.setenv("AGENT_MODE", "bedrock")
    monkeypatch.setattr(guardrail, "_bedrock", lambda: FakeBedrock(fail=True))
    r = guardrail.check("x", "OUTPUT")
    assert r["action"] == "ERROR" and "jane@example.com" not in r["error"]
