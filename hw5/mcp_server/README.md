# Campus Customs MCP Server

This FastMCP server exposes read-only checks, approval-gated payments, and
evidence-gated internal desk actions. Shop reads and writes use only
`data/campus_customs_new.db`; reset reads but never writes the original.

## Tools

- `check_inventory_and_vendor`: checks SKU/size stock, shortage quantity, a
  ticket-linked vendor, lead time, and open invoices. The paid invoice remains
  a vendor link, not proof of a new shipment.
- `check_cash_and_invoices`: checks an invoice or ticket reference, recorded
  payments, cash accounts, and remaining invoice affordability.
- `check_lease_and_rent`: checks a lease or ticket reference using
  `desk.date_today`, payment evidence, and overdue status.
- `get_open_tickets`: returns open tickets and the shop date.
- `list_tickets`: returns all tickets, including dashboard-created and resolved
  tickets, with recorded internal resolutions where present.
- `create_ticket`: validates a subject and description, then atomically creates
  one open ticket with a SQLite-assigned ID and no inferred shop relationships.
- `get_ticket_details`: returns one ticket and records linked by its actual
  nullable fields.
- `get_product_pricing`: returns SKU cost, list price, and derived margin.
- `get_vendor_details`: returns vendor lead times, open invoices, and shipment
  restrictions using declared ticket-to-invoice links where available. It does
  not infer a supplier from product category alone.
- `get_cash_position`: returns cash accounts, payment records, and open invoice
  obligations.
- `get_payment_history`: returns recorded payments and invoice status when an
  invoice reference is supplied.
- `get_shop_date`: returns `desk.date_today` for overdue calculations.
- `assess_ticket_resolution`: read-only check of stock, pricing, linked invoice,
  internal review request, final decision, and unsent draft for Tickets 101/103.
- `record_replenishment_review_request`: idempotently records a Ticket 101
  internal-only review request for the verified shortage and linked vendor. It
  does not place an order or contact the vendor.
- `close_operational_ticket`: conditionally records a final Boss desk decision
  and Customer Service draft and updates Ticket 101 or 103 to `resolved` after
  independent verification. The record explicitly says `not_fulfilled` and
  `unsent_draft`.
- `execute_approved_payment`: atomically applies one explicitly human-approved
  invoice or rent payment after rechecking cash, payment status, and the shop
  date; it cannot create a negative balance or accept an agent identity.
- `resolve_paid_rent_ticket`: conditionally closes Ticket 102 only after its
  declared lease, matching landlord, and full human-approved rent payment are
  verified in the working database.
- `reset_working_database`: restores the working copy from the untouched
  original only when `confirm=true` is explicitly supplied.

The current database has no `lease_id` on Ticket 103, so the lease tool returns
a clear missing-reference result for that ticket instead of inventing a lease.
