"""In-memory conversations and message trees, stored directly in the API (contract) shape.

All access happens on the server's event loop, so no locking is needed. Data is lost on restart; every run
trace is still saved to runs/ and S3 by the pipeline.
"""
import uuid
from datetime import datetime, timezone

from texts import lang_or_default

DEFAULT_TITLE = {"en": "New conversation", "fr": "Nouvelle conversation"}
TITLE_MAX = 60


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Store:
    def __init__(self):
        self.conversations: dict[str, dict] = {}  # id -> Conversation (+ private "_owner")
        self.messages: dict[str, dict[str, dict]] = {}  # conversation id -> {message id -> Message}

    # ---------- conversations ----------

    def create_conversation(self, owner: str, persona_id: str, title: str | None = None, language: str = "en") -> dict:
        lang = lang_or_default(language)
        ts = now_iso()
        conv = {"id": str(uuid.uuid4()), "title": title or DEFAULT_TITLE[lang], "personaId": persona_id,
                "language": lang, "activeLeafId": None, "createdAt": ts, "updatedAt": ts, "_owner": owner,
                "_titled": bool(title)}
        self.conversations[conv["id"]] = conv
        self.messages[conv["id"]] = {}
        return conv

    def get_conversation(self, owner: str, conv_id: str) -> dict | None:
        conv = self.conversations.get(conv_id)
        return conv if conv and conv["_owner"] == owner else None

    def list_conversations(self, owner: str) -> list[dict]:
        mine = [c for c in self.conversations.values() if c["_owner"] == owner]
        return sorted(mine, key=lambda c: (c["updatedAt"], c["createdAt"]), reverse=True)

    def delete_conversation(self, owner: str, conv_id: str) -> bool:
        if not self.get_conversation(owner, conv_id):
            return False
        del self.conversations[conv_id]
        del self.messages[conv_id]
        return True

    def touch(self, conv: dict):
        conv["updatedAt"] = now_iso()

    def auto_title(self, conv: dict, question: str):
        """First question becomes the title, unless the user named the conversation."""
        if not conv["_titled"]:
            q = " ".join(question.split())
            conv["title"] = q if len(q) <= TITLE_MAX else q[:TITLE_MAX - 1].rstrip() + "…"
            conv["_titled"] = True

    # ---------- messages ----------

    def add_message(self, conv: dict, role: str, parent_id: str | None, content: str, status: str,
                    language: str) -> dict:
        msg = {"id": str(uuid.uuid4()), "conversationId": conv["id"], "parentId": parent_id, "role": role,
               "content": content, "status": status, "language": lang_or_default(language), "trace": [],
               "final": None, "createdAt": now_iso()}
        self.messages[conv["id"]][msg["id"]] = msg
        self.touch(conv)
        return msg

    def get_message(self, conv_id: str, msg_id: str | None) -> dict | None:
        return self.messages.get(conv_id, {}).get(msg_id or "")

    def list_messages(self, conv_id: str) -> list[dict]:
        return sorted(self.messages.get(conv_id, {}).values(), key=lambda m: m["createdAt"])

    def path_to(self, conv_id: str, msg_id: str | None) -> list[dict]:
        """Messages from the root down to msg_id (inclusive), following parentId."""
        out, seen = [], set()
        cur = self.get_message(conv_id, msg_id)
        while cur and cur["id"] not in seen:
            seen.add(cur["id"])
            out.append(cur)
            cur = self.get_message(conv_id, cur["parentId"])
        return out[::-1]

    def history_before(self, conv_id: str, user_msg: dict) -> list[dict]:
        """Earlier completed turns [{"question", "answer"}] on the branch that leads to user_msg.
        Short-reply turns (greeting, about, off-topic) also carry "intent"; ChatSession filters them."""
        path = self.path_to(conv_id, user_msg["parentId"])
        turns = []
        for i in range(len(path) - 1):
            q, a = path[i], path[i + 1]
            if q["role"] == "user" and a["role"] == "assistant" and a["status"] == "complete" and a["content"]:
                turn = {"question": q["content"], "answer": a["content"]}
                if a.get("_intent"):
                    turn["intent"] = a["_intent"]
                turns.append(turn)
        return turns


def public(obj: dict) -> dict:
    """Drop private keys (leading underscore) before sending."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}
