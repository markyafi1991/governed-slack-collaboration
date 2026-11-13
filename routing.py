from __future__ import annotations
import json, re
from dataclasses import dataclass
from html import escape
from coordinator import Employee, Message, MAX_QUESTION_LENGTH, run_turn

EMPLOYEE_ID = re.compile(r"[a-z][a-z0-9-]{0,31}")


TIMESTAMP = re.compile(r"[0-9]{1,16}\.[0-9]{6}")


@dataclass(frozen=True)
class Office:
    workspace: str
    channel: str
    users: frozenset[str]
    employees: dict[str, Employee]


@dataclass(frozen=True)
class Turn:
    event_id: str
    thread_ts: str
    employee_id: str
    question: str


def slack_id(value, prefixes):
    return isinstance(value, str) and re.fullmatch(f"[{prefixes}][A-Z0-9]{{2,31}}", value) is not None


def load_office(path):
    with path.open("rb") as stream:
        raw = stream.read(262145)
    if len(raw) > 262144:
        raise ValueError("The office config is too large")
    cfg = json.loads(raw)
    if not isinstance(cfg, dict) or set(cfg) != {"workspace", "channel", "users", "employees"}:
        raise ValueError("Expected workspace, channel, users and employees in the office config")
    if not slack_id(cfg["workspace"], "T") or not slack_id(cfg["channel"], "CG"):
        raise ValueError("Use exact Slack workspace and channel IDs")
    users = cfg["users"]
    if not isinstance(users, list) or not users or not all(slack_id(user, "UW") for user in users):
        raise ValueError("Provide an explicit list of Slack user IDs")
    roster = cfg["employees"]
    if not isinstance(roster, list) or not 1 <= len(roster) <= 12:
        raise ValueError("Configure one to twelve employees")
    employees = {}
    for item in roster:
        keys = {"employee_id", "display_name", "provider", "model", "instructions"}
        if not isinstance(item, dict) or set(item) != keys or not all(isinstance(v, str) for v in item.values()):
            raise ValueError("Each employee needs an ID, display name, provider, model and instructions")
        employee = Employee(**item)
        if (not EMPLOYEE_ID.fullmatch(employee.employee_id) or employee.employee_id in employees
                or not re.fullmatch(r"[\w .-]{1,60}", employee.display_name)
                or employee.provider not in {"openai", "xai"}
                or not employee.model.strip() or not employee.instructions.strip()):
            raise ValueError("Invalid or duplicate employee configuration")
        employees[employee.employee_id] = employee
    return Office(cfg["workspace"], cfg["channel"], frozenset(users), employees)


def select_turn(office, bot_user, payload):
    if (not isinstance(payload, dict) or payload.get("type") != "event_callback"
            or payload.get("team_id") != office.workspace or payload.get("is_ext_shared_channel")):
        return None
    event = payload.get("event")
    event_id = payload.get("event_id")
    if (not isinstance(event, dict) or event.get("type") != "app_mention"
            or event.get("channel") != office.channel or not isinstance(event.get("user"), str)
            or event["user"] not in office.users or event["user"] == bot_user
            or event.get("bot_id") or event.get("bot_profile") or event.get("subtype") is not None
            or not isinstance(event_id, str) or not re.fullmatch(r"Ev[A-Za-z0-9]{3,64}", event_id)):
        return None
    thread_ts = event.get("thread_ts", event.get("ts"))
    text = event.get("text")
    if (not isinstance(thread_ts, str) or not TIMESTAMP.fullmatch(thread_ts)
            or not isinstance(text, str) or len(text) > MAX_QUESTION_LENGTH + 80):
        return None
    parts = text.strip().split(None, 2)
    if len(parts) != 3:
        return None
    mention, employee, question = parts
    if mention != f"<@{bot_user}>" or employee not in office.employees or not question.strip():
        return None
    if len(question) > MAX_QUESTION_LENGTH:
        return None
    return Turn(event_id, thread_ts, employee, question)


def init_receipts(db):
    db.execute("CREATE TABLE IF NOT EXISTS received_events (event_id TEXT PRIMARY KEY) WITHOUT ROWID")


def deliver(db, office, turn, complete, send):
    with db:
        inserted = db.execute("INSERT OR IGNORE INTO received_events VALUES (?)", (turn.event_id,)).rowcount
    if not inserted:
        return False

    def post(message: Message):
        text = escape(f"{message.display_name}\n{message.text}", quote=False)
        send(channel=office.channel, thread_ts=turn.thread_ts, text=text, mrkdwn=False,
             parse="none", link_names=False, unfurl_links=False, unfurl_media=False)

    run_turn(office.employees, turn.employee_id, turn.question, complete, post)
    return True

