"""Safety checks run only against a temporary copy of the working database."""

from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from mcp_server import server


TEE_DRAFT = (
    "Hi Tauhid, the Bulldog tee in size S is currently out of stock. "
    "Would you consider an alternative size or style? We have not confirmed "
    "a replenishment date. This is an unsent draft for human review."
)
HOODIE_DRAFT = (
    "Hi Yale AI Club, we have 8 size-M hoodies available of the 20 requested. "
    "We can’t offer 20 units or a bulk discount now because "
    "additional stock is unconfirmed. This is an unsent draft for human review."
)
REASON = "Verified the current stock and relevant records; this is a final internal desk decision only."


class OperationalClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "working.db"
        shutil.copy2(server.DB_PATH, self.db_path)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("UPDATE tickets SET status = 'open' WHERE id IN (101, 103)")
            if server._table_exists(connection, "ticket_resolution_records"):
                connection.execute("DELETE FROM ticket_resolution_records WHERE ticket_id IN (101, 103)")
            if server._table_exists(connection, "replenishment_review_requests"):
                connection.execute("DELETE FROM replenishment_review_requests WHERE ticket_id = 101")
        self.patch = patch.object(server, "DB_PATH", self.db_path)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def test_review_request_and_ticket_101_closure_are_distinct(self) -> None:
        before = server.close_operational_ticket(
            101, "unavailable_request_alternative", TEE_DRAFT, REASON
        )
        self.assertFalse(before["ok"])
        first = server.record_replenishment_review_request(101)
        self.assertTrue(first["ok"])
        self.assertTrue(first["changed"])
        self.assertEqual(first["request"]["status"], "internal_review_only")
        duplicate_request = server.record_replenishment_review_request(101)
        self.assertTrue(duplicate_request["ok"])
        self.assertFalse(duplicate_request["changed"])
        self.assertFalse(server.close_operational_ticket(
            101, "unavailable_request_alternative",
            "The tee is available now and guaranteed delivery tomorrow.", REASON
        )["ok"])
        result = server.close_operational_ticket(
            101, "unavailable_request_alternative", TEE_DRAFT, REASON
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["fulfillment_status"], "not_fulfilled")
        self.assertEqual(result["communication_status"], "unsent_draft")
        self.assertFalse(server.close_operational_ticket(
            101, "unavailable_request_alternative", TEE_DRAFT, REASON
        )["ok"])
        assessment = server.assess_ticket_resolution(101)
        self.assertTrue(assessment["can_close"])
        self.assertEqual(assessment["available_quantity"], 0)

    def test_ticket_103_decline_has_no_discount_or_cash_effect(self) -> None:
        self.assertFalse(server.close_operational_ticket(
            103, "unavailable_request_alternative", HOODIE_DRAFT, REASON
        )["ok"])
        result = server.close_operational_ticket(
            103, "decline_unfulfillable_bulk_request", HOODIE_DRAFT, REASON
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["shortage_at_decision"], 12)
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(connection.execute(
                "SELECT balance FROM cash_accounts WHERE name = 'checking'"
            ).fetchone()[0], 160.0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM payments").fetchone()[0], 2)
            self.assertEqual(connection.execute(
                "SELECT status FROM tickets WHERE id = 102"
            ).fetchone()[0], "resolved")
            self.assertEqual(connection.execute(
                "SELECT communication_status FROM ticket_resolution_records WHERE ticket_id = 103"
            ).fetchone()[0], "unsent_draft")


if __name__ == "__main__":
    unittest.main()
