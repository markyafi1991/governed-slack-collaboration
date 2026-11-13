"""No Slack connection, model request, credential or persisted conversation."""
import json
from pathlib import Path
import sqlite3
import routing


def fixture():
    office = routing.load_office(Path(__file__).parent / "examples/office.json")
    payload = {"type":"event_callback", "team_id":"TFIXTURE", "event_id":"EvFixture01",
               "event":{"type":"app_mention", "user":"UOWNER", "channel":"CFIXTURE",
                        "ts":"1760000000.123456", "text":"<@UTRANSPORT> operations Review a fictional launch."}}
    return office, payload


def complete(employee, instructions, question):
    if employee.employee_id == "operations":
        return json.dumps({"message":"The fictional launch needs a support readiness check.",
                           "handoff":{"employee":"risk", "question":"What should we verify?"}})
    return "Exercise the synthetic support-volume failure case before deciding."


def main():
    office, payload = fixture()
    turn = routing.select_turn(office, "UTRANSPORT", payload)
    with sqlite3.connect(":memory:") as db:
        routing.init_receipts(db)
        messages = []
        accepted = routing.deliver(db, office, turn, complete, lambda **message: messages.append(message))
        repeated = routing.deliver(db, office, turn, complete, lambda **message: messages.append(message))
        print(json.dumps({"synthetic":True, "accepted":accepted, "repeat_accepted":repeated,
                          "messages":messages, "network_transport_included":False, "live_acceptance":False}, indent=2))


if __name__ == "__main__":
    main()
