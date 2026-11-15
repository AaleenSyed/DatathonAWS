"""Pipeline tests with a fake boss and fake presenter (no Bedrock): real tools, reviewer, retries and trace."""
import json

import pytest

import agent_tools as at
import pipeline
from workers import data_retriever as dr

pytestmark = pytest.mark.skipif(not (dr.DATA_DIR / "macro_extra.csv").exists(),
                                reason="needs starter data + data/macro_extra.csv")
Q = "I want to put a big part of my savings in NVDA, good idea?"
PLAN = {"requested_targets": ["NVDA"], "recommended_sectors": ["Consumer Staples"],
        "conflicts_found": ["single stock cap"], "reasoning_notes": "assumed 50%"}


@pytest.fixture(autouse=True)
def no_s3(monkeypatch):
    monkeypatch.setenv("TRACE_S3", "0")
    monkeypatch.setenv("SEMANTIC_CHECK", "0")  # no Bedrock in offline tests; fakes below


class FakeBoss:
    """Calls the real tools. skip = set of (action, target) it 'forgets' on the first `forget_rounds` calls."""
    def __init__(self, skip=(), forget_rounds=1, extra=()):
        self.calls, self.skip, self.forget_rounds, self.extra = [], set(skip), forget_rounds, extra

    def __call__(self, prompt):
        self.calls.append(prompt)
        forget = len(self.calls) <= self.forget_rounds
        todo = [("cycle_phase", None), ("fear_hope", None), ("analyze_asset", "NVDA"),
                ("check_suitability", "NVDA"), ("analyze_sector", "Consumer Staples"),
                ("sector_momentum", "Consumer Staples"), ("check_suitability", "Consumer Staples"), *self.extra]
        for action, target in todo:
            if forget and (action, target) in self.skip:
                continue
            fn = getattr(at, action)
            fn() if target is None else fn(target)
        return dict(PLAN)


def vol_text(trace):
    step = next(s for s in trace.steps if s["action"] == "analyze_asset")
    return f"NVDA volatility is {step['output']['data']['annualized_vol']:.1%} [fact: step {step['step']}]."


class FakePresenter:
    def __init__(self, bad_first=0):
        self.calls, self.bad_first = [], bad_first

    def __call__(self, persona, question, history, trace, plan, notes, feedback=None):
        self.calls.append({"feedback": feedback, "notes": notes, "history": list(history)})
        if len(self.calls) <= self.bad_first:
            return "NVDA volatility is 9876.5% [fact: step 1]."
        return vol_text(trace)


def session(tmp_path, persona="robert", boss=None, presenter=None):
    return pipeline.ChatSession(persona, boss=boss or FakeBoss(), presenter=presenter or FakePresenter(),
                                runs_dir=tmp_path)


def test_happy_path_and_trace_saved(tmp_path):
    r = session(tmp_path).ask(Q)
    assert r["work_verdict"]["verdict"] == "pass" and r["answer_verdict"]["verdict"] == "pass"
    assert "Not personalized financial advice" in r["answer"]  # disclaimer always present
    saved = json.loads(open(r["saved"]["local"], encoding="utf-8").read())
    actors = [s["actor"] for s in saved["steps"]]
    assert actors[0] == "user" and actors[-1] == "pipeline" and "reviewer" in actors and "presenter" in actors
    assert all({"step", "actor", "action", "input", "output_summary", "timestamp"} <= set(s) for s in saved["steps"])
    assert r["saved"]["s3"] is None  # disabled in tests
    assert at.CONTEXT["trace"] is None  # context cleared after the turn


def test_reviewer_catches_incomplete_work_and_retries(tmp_path):
    boss = FakeBoss(skip={("check_suitability", "NVDA")})
    r = session(tmp_path, boss=boss).ask(Q)
    reviews = [s["output"]["verdict"] for s in r["trace"].steps if s["action"] == "review_work"]
    assert reviews == ["fail", "pass"] and len(boss.calls) == 2
    assert boss.calls[1].startswith("REVIEWER FAIL") and "'NVDA' has no successful check_suitability" in boss.calls[1]
    assert "incomplete" not in r["answer"].lower()


def test_gives_up_after_two_retries_with_incomplete_note(tmp_path):
    boss = FakeBoss(skip={("check_suitability", "NVDA")}, forget_rounds=99)
    presenter = FakePresenter()
    r = session(tmp_path, boss=boss, presenter=presenter).ask(Q)
    assert len(boss.calls) == 1 + pipeline.MAX_REVIEW_RETRIES
    assert r["work_verdict"]["verdict"] == "fail"
    assert "analysis is incomplete" in r["answer"] and presenter.calls[0]["notes"]


def test_presenter_retry_on_unsupported_number(tmp_path):
    presenter = FakePresenter(bad_first=1)
    r = session(tmp_path, presenter=presenter).ask(Q)
    assert len(presenter.calls) == 2 and "9876.5" in presenter.calls[1]["feedback"]
    assert r["answer_verdict"]["verdict"] == "pass" and "9876.5%" not in r["answer"]


def test_presenter_never_fixes_gets_reviewer_note(tmp_path):
    presenter = FakePresenter(bad_first=99)
    r = session(tmp_path, presenter=presenter).ask(Q)
    assert len(presenter.calls) == 1 + pipeline.MAX_ANSWER_RETRIES
    assert "Reviewer note" in r["answer"] and r["answer_verdict"]["verdict"] == "fail"


def test_answer_numbers_all_in_trace(tmp_path):
    import reviewer
    r = session(tmp_path).ask(Q)
    assert reviewer.check_answer(r["answer"], r["trace"])["verdict"] == "pass"


def test_tool_error_is_recorded_not_raised(tmp_path):
    boss = FakeBoss(extra=[("analyze_sector", "Nope")])
    r = session(tmp_path, boss=boss).ask(Q)
    err = [s for s in r["trace"].steps if s["action"] == "analyze_sector" and s["output"]["status"] == "error"]
    assert err and "unknown sector" in err[0]["output_summary"]


def test_boss_exception_is_recorded(tmp_path):
    def broken(prompt):
        raise RuntimeError("bedrock down")
    r = session(tmp_path, boss=broken).ask(Q)
    assert r["work_verdict"]["verdict"] == "fail"
    assert any(s["action"] == "plan_error" for s in r["trace"].steps)


def test_multi_turn_history(tmp_path):
    presenter = FakePresenter()
    s = session(tmp_path, presenter=presenter)
    s.ask(Q)
    r2 = s.ask("And what about a smaller amount?")
    assert r2["trace"].meta["turn"] == 2 and presenter.calls[-1]["history"][0]["question"] == Q


def test_persona_is_fixed_by_session(tmp_path):
    r = session(tmp_path, persona="amira").ask(Q)
    suit = [s for s in r["trace"].steps if s["action"] == "check_suitability"]
    assert suit and all(s["input"]["persona"] == "amira" for s in suit)


def test_unknown_persona():
    with pytest.raises(ValueError):
        pipeline.ChatSession("bob", boss=FakeBoss(), presenter=FakePresenter())


def test_no_stress_tool_before_end_of_2022(tmp_path):
    at.CONTEXT.update(trace=None, persona="robert", as_of="2022-06-30")
    try:
        r = at.stress_test_2022("SPY")
    finally:
        at.CONTEXT["as_of"] = "2026-11-12"
    assert r["status"] == "error" and "before the end of 2022" in r["error"]


# ---------- semantic (Haiku) check, with a fake checker ----------

class FakeSemantic:
    def __init__(self, fail_first=0, raise_error=False):
        self.calls, self.fail_first, self.raise_error = [], fail_first, raise_error

    def __call__(self, answer, trace):
        self.calls.append(answer)
        if self.raise_error:
            raise RuntimeError("throttled")
        if len(self.calls) <= self.fail_first:
            return {"verdict": "fail", "reasons": ['"held up better": evidence shows it did worse'], "issues": []}
        return {"verdict": "pass", "reasons": [], "issues": []}


def test_semantic_fail_triggers_rewrite(tmp_path):
    presenter, sem = FakePresenter(), FakeSemantic(fail_first=1)
    r = pipeline.ChatSession("robert", boss=FakeBoss(), presenter=presenter, runs_dir=tmp_path, semantic=sem).ask(Q)
    assert len(presenter.calls) == 2 and "held up better" in presenter.calls[1]["feedback"]
    assert r["answer_verdict"]["verdict"] == "pass"
    steps = [s for s in r["trace"].steps if s["action"] == "semantic_check"]
    assert [s["output"]["verdict"] for s in steps] == ["fail", "pass"]


def test_semantic_runs_only_after_numbers_pass(tmp_path):
    sem = FakeSemantic()
    pipeline.ChatSession("robert", boss=FakeBoss(), presenter=FakePresenter(bad_first=1), runs_dir=tmp_path,
                         semantic=sem).ask(Q)
    assert len(sem.calls) == 1  # the bad-number draft never reached the LLM check


def test_semantic_never_fixed_gets_reviewer_note(tmp_path):
    sem = FakeSemantic(fail_first=99)
    r = pipeline.ChatSession("robert", boss=FakeBoss(), presenter=FakePresenter(), runs_dir=tmp_path,
                             semantic=sem).ask(Q)
    assert "Reviewer note" in r["answer"] and "held up better" in r["answer"]


def test_semantic_error_does_not_block(tmp_path):
    r = pipeline.ChatSession("robert", boss=FakeBoss(), presenter=FakePresenter(), runs_dir=tmp_path,
                             semantic=FakeSemantic(raise_error=True)).ask(Q)
    assert r["answer_verdict"]["verdict"] == "pass" and "Reviewer note" not in r["answer"]
    assert any(s["action"] == "semantic_check" and "unavailable" in s["output_summary"] for s in r["trace"].steps)


def test_semantic_off_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SEMANTIC_CHECK", "0")
    assert pipeline.ChatSession("robert", boss=FakeBoss(), presenter=FakePresenter()).semantic is None
    monkeypatch.setenv("SEMANTIC_CHECK", "1")
    assert pipeline.ChatSession("robert", boss=FakeBoss(), presenter=FakePresenter()).semantic is not None
