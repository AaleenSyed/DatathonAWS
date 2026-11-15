"""Terminal chatbot: pick a persona, then ask questions (multi-turn).

    python chat.py
Commands: /trace (steps of the last answer), /persona (switch persona), /quit
"""
import sys

from personas import PERSONAS
from pipeline import ChatSession

BANNER = ("AlphaForge AI: educational simulation for fictional investor personas. "
          "Not personalized financial advice. No real transactions.")


def pick_persona() -> str:
    keys = sorted(PERSONAS)
    for i, k in enumerate(keys, 1):
        p = PERSONAS[k]
        print(f"  {i}. {p['name']}, {p['age']}, {p['occupation']}: risk {p['risk_tolerance']}, "
              f"horizon {p['horizon_years']} years, goal: {p['goal']}")
    while True:
        c = input("Pick a persona (1-3): ").strip()
        if c.isdigit() and 1 <= int(c) <= len(keys):
            return keys[int(c) - 1]
        if c.lower() in PERSONAS:
            return c.lower()


def show_trace(result):
    t = result["trace"]
    print(f"\nTrace {t.run_id} ({len(t.steps)} steps)")
    for s in t.steps:
        print(f"  {s['step']:>2}. {s['actor']:<26} {s['action']:<20} {s['output_summary'][:90]}")
    print(f"  saved: {result['saved']['local']}" + (f" | {result['saved']['s3']}" if result['saved']['s3'] else ""))
    if result["saved"]["warning"]:
        print(f"  warning: {result['saved']['warning']}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252 (answers use em dashes)
    print(BANNER)
    session, last = ChatSession(pick_persona()), None
    print(f"\nChatting as {session.persona['name']}. Ask a question (/trace, /persona, /quit).")
    while True:
        try:
            q = input(f"\n{session.persona['name']}> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q == "/quit":
            break
        if q == "/trace":
            show_trace(last) if last else print("No answer yet.")
            continue
        if q == "/persona":
            session, last = ChatSession(pick_persona()), None
            continue
        print("...analyzing (boss -> workers -> reviewer -> presenter)")
        last = session.ask(q)
        print("\n" + last["answer"])
        print(f"\n[work review: {last['work_verdict']['verdict']} | answer check: {last['answer_verdict']['verdict']}"
              f" | trace: {last['saved']['local']}]")


if __name__ == "__main__":
    sys.exit(main())
