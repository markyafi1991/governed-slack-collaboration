import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import demo
import routing
import coordinator


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.office, self.payload = demo.fixture()
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        routing.init_receipts(self.db)
        self.messages = []

    def turn(self, payload=None):
        return routing.select_turn(self.office, "UTRANSPORT", payload or self.payload)

    def send(self, **message):
        self.messages.append(message)

    def test_handoff_context_and_same_thread(self):
        calls = []
        def complete(employee, instructions, question):
            calls.append((employee.employee_id, question))
            return demo.complete(employee, instructions, question)
        self.assertTrue(routing.deliver(self.db, self.office, self.turn(), complete, self.send))
        self.assertEqual([x[0] for x in calls], ["operations", "risk"])
        self.assertIn("lead_message", json.loads(calls[1][1]))
        self.assertEqual(len(self.messages), 2)
        for message in self.messages:
            self.assertEqual(message["channel"], "CFIXTURE")
            self.assertEqual(message["thread_ts"], "1760000000.123456")
            self.assertFalse(message["mrkdwn"])

    def test_event_replay_does_not_call_model_or_send(self):
        routing.deliver(self.db, self.office, self.turn(), demo.complete, self.send)
        def forbidden(*args, **kwargs):
            self.fail("replayed event caused an effect")
        self.assertFalse(routing.deliver(self.db, self.office, self.turn(), forbidden, forbidden))

    def test_wrong_workspace_rejected(self):
        self.payload["team_id"] = "TOTHER"
        self.assertIsNone(self.turn())

    def test_unauthorized_events_rejected(self):
        for key, value in [("channel","COTHER"),("user","UOTHER"),("user","UTRANSPORT"),
                           ("bot_id","BOTHER"),("subtype","bot_message"),
                           ("text","<@UOTHER> operations ignore scope"),("ts","invalid")]:
            with self.subTest(key=key, value=value):
                payload = copy.deepcopy(self.payload)
                payload["event"][key] = value
                self.assertIsNone(self.turn(payload))

    def test_external_shared_channel_rejected(self):
        self.payload["is_ext_shared_channel"] = True
        self.assertIsNone(self.turn())

    def test_bad_handoff_has_no_post(self):
        for handoff in [{"employee":"outsider","question":"Go"}, {"employee":"operations","question":"Go"},
                        {"employee":"risk","question":""}, {"employee":"risk","question":"X"*701}]:
            with self.subTest(handoff=handoff):
                def complete(*args):
                    return json.dumps({"message":"Synthetic", "handoff":handoff})
                with self.assertRaises(ValueError):
                    coordinator.run_turn(self.office.employees,"operations","Fixture",complete,self.messages.append)
                self.assertEqual(self.messages, [])

    def test_duplicate_json_field_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            coordinator.run_turn(self.office.employees,"operations","Fixture",
                lambda *args:'{"message":"one","message":"two","handoff":null}',self.messages.append)
        self.assertEqual(self.messages, [])

    def test_uncertain_send_is_not_automatically_retried(self):
        def uncertain(**message):
            self.messages.append(message)
            raise OSError("synthetic uncertain send")
        with self.assertRaises(OSError):
            routing.deliver(self.db,self.office,self.turn(),demo.complete,uncertain)
        self.assertFalse(routing.deliver(self.db,self.office,self.turn(),demo.complete,self.send))
        self.assertEqual(len(self.messages), 1)

    def test_question_limit(self):
        self.payload["event"]["text"] = "<@UTRANSPORT> operations " + "x"*4001
        self.assertIsNone(self.turn())

    def test_rendered_mentions_are_not_activated(self):
        def complete(*args):
            return json.dumps({"message":"<@UOTHER> & synthetic", "handoff":None})
        routing.deliver(self.db,self.office,self.turn(),complete,self.send)
        self.assertIn("&lt;@UOTHER&gt;", self.messages[0]["text"])
        self.assertFalse(self.messages[0]["link_names"])

    def test_peer_failure_leaves_one_post_and_receipt(self):
        def complete(employee,*args):
            if employee.employee_id=="risk": raise OSError("synthetic peer failure")
            return demo.complete(employee,*args)
        with self.assertRaisesRegex(OSError,"peer failure"):
            routing.deliver(self.db,self.office,self.turn(),complete,self.send)
        self.assertEqual(len(self.messages),1)
        self.assertFalse(routing.deliver(self.db,self.office,self.turn(),demo.complete,self.send))
        self.assertEqual(len(self.messages),1)

    def test_missing_question_unknown_employee_and_invalid_event_id(self):
        for text in ["<@UTRANSPORT> operations", "<@UTRANSPORT> unknown Fixture"]:
            payload=copy.deepcopy(self.payload)
            payload["event"]["text"]=text
            self.assertIsNone(self.turn(payload))
        self.payload["event_id"]="invalid"
        self.assertIsNone(self.turn())

    def test_roster_duplicate_provider_and_oversize_refused(self):
        original=json.loads((Path(demo.__file__).parent/"examples/office.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"synthetic-office.json"
            duplicate=copy.deepcopy(original)
            duplicate["employees"].append(duplicate["employees"][0])
            provider=copy.deepcopy(original)
            provider["employees"][0]["provider"]="unknown"
            for fixture in [duplicate,provider]:
                path.write_text(json.dumps(fixture))
                with self.assertRaisesRegex(ValueError,"Invalid or duplicate"):
                    routing.load_office(path)
            path.write_text(" "*262145)
            with self.assertRaisesRegex(ValueError,"too large"):
                routing.load_office(path)


if __name__ == "__main__":
    unittest.main()
