"""Run a single visible conversation with at most one employee handoff."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass


MAX_QUESTION_LENGTH = 4_000
MAX_MESSAGE_LENGTH = 3_000
MAX_HANDOFF_QUESTION_LENGTH = 700
MAX_MODEL_REPLY_LENGTH = 24_000


@dataclass(frozen=True)
class Employee:
    employee_id: str
    display_name: str
    provider: str
    model: str
    instructions: str


@dataclass(frozen=True)
class Message:
    employee_id: str
    display_name: str
    text: str


def _bounded_text(value: object, limit: int, label: str) -> str:
    if not isinstance(value, str) or len(value) > limit or not value.strip():
        raise ValueError(f"{label} must contain 1 to {limit} characters.")
    return value.strip()


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("The lead reply contains a duplicate JSON field.")
        fields[key] = value
    return fields


def run_turn(
    employees: Mapping[str, Employee],
    first_id: str,
    question: str,
    complete: Callable[[Employee, str, str], str],
    post: Callable[[Message], None],
) -> None:
    """Post the lead reply, then pass its visible context to one selected peer."""
    question = _bounded_text(question, MAX_QUESTION_LENGTH, "Question")
    lead = employees.get(first_id)
    if lead is None or lead.employee_id != first_id:
        raise ValueError("The requested employee is not in the roster.")

    peers = {
        employee_id: employee.display_name
        for employee_id, employee in employees.items()
        if employee_id == employee.employee_id and employee_id != first_id
    }
    lead_instructions = (
        f"You are {lead.display_name}.\n{lead.instructions}\n\n"
        'Return exactly one JSON object with "message" and "handoff" fields. '
        f'Write the visible answer in "message", up to {MAX_MESSAGE_LENGTH} characters. '
        'Set "handoff" to null if you can finish on your own. '
        'To ask a peer for input, set "handoff" to an object with "employee" '
        f'(an exact roster ID) and "question" (up to {MAX_HANDOFF_QUESTION_LENGTH} characters). '
        'The answer and any handoff question will be visible in the Slack thread. '
        f"Eligible peers by ID and display name: {json.dumps(peers, ensure_ascii=False)}"
    )
    raw_reply = _bounded_text(
        complete(lead, lead_instructions, question), MAX_MODEL_REPLY_LENGTH, "Lead reply"
    )
    try:
        reply = json.loads(raw_reply, object_pairs_hook=_unique_fields)
    except (json.JSONDecodeError, RecursionError):
        raise ValueError("The lead reply must be a JSON message with a handoff field.") from None
    if not isinstance(reply, dict) or set(reply) != {"message", "handoff"}:
        raise ValueError("The lead reply must contain exactly message and handoff fields.")
    visible = _bounded_text(reply["message"], MAX_MESSAGE_LENGTH, "Lead message")

    handoff = reply["handoff"]
    if handoff is None:
        post(Message(lead.employee_id, lead.display_name, visible))
        return

    if not isinstance(handoff, dict) or set(handoff) != {"employee", "question"}:
        raise ValueError("A handoff must contain exactly an employee and a question.")
    peer_id = handoff["employee"]
    if not isinstance(peer_id, str) or peer_id not in peers:
        raise ValueError("A handoff must name a different employee in the roster.")
    peer = employees[peer_id]
    peer_question = _bounded_text(
        handoff["question"], MAX_HANDOFF_QUESTION_LENGTH, "Handoff question"
    )
    post(Message(
        lead.employee_id,
        lead.display_name,
        f"{visible}\n\nHandoff to {peer.display_name}\n{peer_question}",
    ))

    peer_instructions = (
        f"You are {peer.display_name}.\n{peer.instructions}\n\n"
        "Answer the handoff question in plain text. The lead's visible message is context. "
        f"Give one reply, up to {MAX_MESSAGE_LENGTH} characters. This is the final turn."
    )
    peer_input = json.dumps({"question": peer_question, "lead_message": visible}, ensure_ascii=False)
    peer_reply = _bounded_text(
        complete(peer, peer_instructions, peer_input), MAX_MESSAGE_LENGTH, "Peer reply"
    )
    post(Message(peer.employee_id, peer.display_name, peer_reply))
