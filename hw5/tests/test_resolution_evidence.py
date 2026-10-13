"""Read-only integration checks against the existing working database."""

import unittest

from backend.mcp_client import MCPToolClient


class ResolutionEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_linked_vendor_survives_invoice_payment(self) -> None:
        async with MCPToolClient() as client:
            inventory = await client.call(
                "check_inventory_and_vendor", {"sku": "CC-TEE-WHITE", "size": "S"}
            )
            vendor = await client.call(
                "get_vendor_details", {"sku": "CC-TEE-WHITE", "size": "S"}
            )
            evidence = await client.call("assess_ticket_resolution", {"ticket_id": 101})
        self.assertTrue(inventory["ok"])
        self.assertEqual(inventory["vendor"]["name"], "Bulldog Print Co")
        self.assertEqual(inventory["lead_time_days"], 5)
        self.assertEqual(inventory["linked_invoices"][0]["status"], "paid")
        self.assertEqual(inventory["open_unpaid_invoices"], [])
        self.assertIsNone(inventory["vendor_can_ship"])
        self.assertEqual(vendor["vendors"][0]["id"], 1)
        self.assertEqual(evidence["can_close"], evidence["ticket_status"] == "resolved")
        self.assertEqual(evidence["available_quantity"], 0)

    async def test_hoodie_has_no_verified_supplier_or_closure(self) -> None:
        async with MCPToolClient() as client:
            inventory = await client.call(
                "check_inventory_and_vendor", {"sku": "CC-HOOD-NAVY", "size": "M"}
            )
            vendor = await client.call(
                "get_vendor_details", {"sku": "CC-HOOD-NAVY", "size": "M"}
            )
            evidence = await client.call("assess_ticket_resolution", {"ticket_id": 103})
        self.assertTrue(vendor["ok"])
        if evidence["ticket_status"] == "open":
            self.assertEqual(inventory["requested_quantity"], 20)
            self.assertEqual(inventory["shortage"]["quantity"], 12)
        self.assertEqual(vendor["vendors"], [])
        self.assertEqual(evidence["can_close"], evidence["ticket_status"] == "resolved")
        self.assertEqual(evidence["available_quantity"], 8)
        self.assertEqual(evidence["shortage_quantity"], 12)
        self.assertEqual(evidence["pricing"]["unit_cost"], 22.0)
        self.assertEqual(evidence["pricing"]["list_price"], 58.0)


if __name__ == "__main__":
    unittest.main()
