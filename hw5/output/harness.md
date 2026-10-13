# Problem 2: Database Tables

### `cash_accounts`

Fields: `name`, `balance`, `date`.

Matters to agents because it records available cash balances.

### `desk`

Fields: `date_today`, `notes`.

Matters to agents because it provides the desk's current date and notes.

### `inventory`

Fields: `sku`, `name`, `size`, `qty`, `location`.

Matters to agents because it records item quantities and locations.

### `invoices`

Fields: `id`, `vendor_id`, `amount`, `due_date`, `status`, `description`.

Matters to agents because it records vendor bills and their payment status.

### `leases`

Fields: `id`, `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes`.

Matters to agents because it records rental spaces, rent, landlords, and due dates.

### `payments`

Fields: `id`, `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by`.

Matters to agents because it records payment transactions and approvals.

### `pricing`

Fields: `sku`, `unit_cost`, `list_price`.

Matters to agents because it provides item costs and list prices.

### `tickets`

Fields: `id`, `type`, `requester`, `subject`, `sku`, `size`, `qty`, `lease_id`, `invoice_id`, `status`, `notes`, `created_at`.

Matters to agents because it contains the requests they must route and resolve.

### `vendors`

Fields: `id`, `name`, `specialty`, `lead_days`.

Matters to agents because it provides vendor identities, specialties, and lead times.

### Problem 9 working-copy operational tables

`replenishment_review_requests` fields: `id`, `ticket_id`, `sku`, `size`, `qty`, `vendor_id`, `status`, `shop_date`. It records one internal-only sourcing review for Ticket 101; it is not a purchase order or shipment.

`ticket_resolution_records` fields: `ticket_id`, `decision`, `customer_draft`, `boss_reasoning`, `shop_date`, `stock_at_decision`, `shortage_at_decision`, `communication_status`, `fulfillment_status`. It preserves the final internal decision and unsent draft separately from physical fulfillment.

## Problem 3 — MCP tools

### `check_inventory_and_vendor`

- Reads: `inventory`, `tickets`, `invoices`, `vendors`.
- Helps unlock Ticket 101.
- It compares the requested product quantity with stock and identifies matching vendor and open-invoice information.

### `check_cash_and_invoices`

- Reads: `tickets`, `invoices`, `cash_accounts`, `payments`.
- Helps inspect a ticket-linked invoice, including Ticket 101's invoice 501.
- It shows invoice and payment status and whether the recorded cash balance covers the remaining invoice amount.

### `check_lease_and_rent`

- Reads: `tickets`, `leases`, `desk`, `payments`, `invoices`.
- Helps unlock Ticket 102.
- It verifies Ticket 102's declared lease, rent due date, and recorded payments using the desk date.

## Problem 5 — Agent team and MCP architecture

### Agents

- **Boss:** Reads and interprets tickets, delegates bounded tasks, coordinates specialist findings, makes final internal desk decisions, requests human approval for commitments, and resolves tickets only after MCP verifies required work.
- **Inventory:** Checks SKU/size stock, calculates shortages, identifies linked vendors and lead times, checks unpaid invoices, and recommends internal sourcing review separately from an actual purchase.
- **Accounting:** Checks cash, invoices, payments, pricing, and margins; prepares affordability and payment proposals without executing payments or allowing negative cash.
- **Facilities:** Checks leases, rent, due dates, payment evidence, and overdue status using `desk.date_today`; coordinates payment proposals with Accounting.
- **Customer Service:** Reviews verified records and prepares complete customer-response drafts for human review; drafts are never sent and never imply unsupported fulfillment.

### MCP tools, tables, and purpose

- `check_inventory_and_vendor`: reads `inventory`, `tickets`, `invoices`, `vendors`; checks SKU/size stock, shortage, and invoice-based vendor evidence.
- `check_cash_and_invoices`: reads `tickets`, `invoices`, `cash_accounts`, `payments`; checks an invoice's remaining amount and affordability.
- `check_lease_and_rent`: reads `tickets`, `leases`, `desk`, `payments`, `invoices`; checks linked rent, due date, and recorded payment status.
- `get_open_tickets`: reads `tickets`, `desk`; lists open work and the shop date.
- `list_tickets`: reads `tickets`, `desk`, and any `ticket_resolution_records`; lists every ticket and its recorded status for the dashboard.
- `create_ticket`: reads `desk` and writes `tickets` in the working database; validates required text, assigns a unique ID through SQLite, and creates an `open` ticket with no inferred relationships.
- `get_ticket_details`: reads `tickets`, `inventory`, `pricing`, `invoices`, `vendors`, `leases`, `payments`, `desk`, and any `ticket_resolution_records`; returns one ticket, verified related records, and its recorded internal outcome if present.
- `get_product_pricing`: reads `pricing`; returns listed cost, price, and derived margin.
- `get_vendor_details`: reads `tickets`, `vendors`, `invoices`; returns linked vendor lead time and open-unpaid restrictions without relying on invoice status for vendor identification.
- `assess_ticket_resolution`: reads `sqlite_master`, `tickets`, `inventory`, `pricing`, `invoices`, `replenishment_review_requests`, `ticket_resolution_records`; reports current facts and recorded internal desk evidence without writes.
- `record_replenishment_review_request`: reads `tickets`, `inventory`, `invoices`, `vendors`, `payments`, `desk`; idempotently writes `replenishment_review_requests` for Ticket 101's verified shortage. No vendor order or cash movement.
- `close_operational_ticket`: reads `tickets`, `inventory`, `invoices`, `pricing`, `desk`, and for 101 `replenishment_review_requests`; atomically writes `ticket_resolution_records` and `tickets` only for a validated final decision and unsent draft.
- `get_cash_position`: reads `cash_accounts`, `payments`, `invoices`; returns live balances, payment records, and open invoices.
- `get_payment_history`: reads `payments`, `invoices`; checks existing payments for an invoice or lease reference.
- `get_shop_date`: reads `desk`; supplies `desk.date_today` for overdue checks.
- `execute_approved_payment`: reads `cash_accounts`, `desk`, `invoices` or `leases`, and `payments`; atomically writes `payments`, `cash_accounts`, and, for a fully paid invoice, `invoices`, only after a human approval and fresh cash/duplicate checks.
- `resolve_paid_rent_ticket`: reads `tickets`, `leases`, `desk`, `payments` and conditionally writes `tickets`; closes Ticket 102 only when its declared lease, matching landlord, and human-approved full rent payment are verified.
- `reset_working_database`: copies all tables from the original database file into the working database file after explicit confirmation; never writes the original.

### Safety guardrails

All shop reads and writes go through MCP and the working database; the original
is never written. Payments require explicit human approval and a fresh cash,
remaining-obligation, and duplicate-payment check, then execute atomically.
No payment may make checking negative. An open unpaid vendor invoice blocks new
shipments, not payment of that invoice. Ticket 101's paid invoice still links
Bulldog Print Co through the declared ticket foreign key; payment does not
prove a new order or stock receipt. Ticket 103 has no supplier link or quote.
No incoming revenue, unverified vendor capability, inventory, purchase price,
or delivery date is assumed. Customer messages remain unsent drafts; purchase
orders and physical restocking are not executable in this workflow. Ticket 102
closes only after verified full rent payment. Tickets 101 and 103 can close as
internal desk tasks after actual specialist work, a Boss final no-commitment
decision, a complete Customer Service draft, and independent atomic MCP checks.
Ticket 101 additionally requires an internal-only replenishment review request.
The stored `not_fulfilled` and `unsent_draft` flags explicitly prevent desk
resolution from being misreported as order fulfillment or customer contact.
No discount was offered or approved for Ticket 103; no further cash moved.

### Runtime controls

- Maximum 8 iterations per ticket.
- Maximum delegation depth 3 and maximum 12 total delegations per ticket.
- Maximum 5 MCP calls per individual agent turn.
- Maximum 3 retries for transient MCP failures.
- Maximum 2,000 model output tokens per agent turn; model tool calls are sequential.
- Identical MCP calls are cached; duplicate delegations are suppressed.
- Context is bounded to recent verified findings rather than full database rows
  or full conversation history.
- Work stops as `completed`, `blocked`, `needs_approval`, or at a configured
  limit, with the stop reason recorded.
- Meaningful agent, tool, delegation, approval, and stop events append to
  `output/audit_trail.json` with bounded arguments and results.

## Problem 7 — FastAPI routes

- `GET /api/tickets`: Returns all working-database tickets, including Tickets 101–103 and new Open tickets, with MCP-verified descriptions, statuses, and any internal resolution record.
- `POST /api/tickets`: Validates subject and description, creates one Open ticket through MCP, and returns its database-assigned ID without running agents.
- `POST /api/tickets/{ticket_id}/run`: Runs the bounded Boss-led team; it never pays, purchases, or contacts customers. Ticket 102 conditionally closes after verified rent payment; 101/103 conditionally close after validated internal decision, specialist draft, and independent MCP checks.
- `GET /api/events`: Returns a configurable-limited slice of append-only activity, optionally filtered by ticket before limiting so older ticket history remains visible.
- `POST /api/approvals/{approval_id}`: Accepts an explicit human approval or rejection; approved payments are rechecked and executed atomically through MCP, while unsupported purchase execution remains blocked.
- `GET /api/cash`: Returns the current checking balance and cash position through MCP.
- `POST /api/reset`: Explicitly restores the working database from the original through MCP after confirming no run or payment is active, while preserving audit history.

## Problem 8–9 — React dashboard

The light-mode React/Vite dashboard displays live backend ticket statuses,
five agent modules, recorded delegations and filterable audit events, checking
cash, and payment approvals. It polls events while work runs, prevents duplicate
run submissions in the UI, requires a human confirmation/name for approval, and
requires a typed confirmation before reset. Run reports are kept in browser
session storage; ticket status and cash always refresh from the backend. The
Ticket Desk can create a new Open ticket from a subject and description without
starting agents, then select it and request a bounded Boss-led run. The UI
shows new tickets immediately and includes them in activity filters. A
dashboard-created ticket has no inferred SKU, invoice, lease, or requester
relationship; unlinked payment proposals cannot be approved or executed, and
there is no generic automatic ticket-closure operation. The standalone
`resolved_board.html` uses genuine captures of the running dashboard
for each ticket's actual final state. The detail panel shows the recorded
internal decision, stock/shortage snapshot, and unsent Customer Service draft
separately from ticket status. Run reports distinguish the agent-run outcome
from the database ticket status, so “Resolved” does not imply fulfillment or
message delivery.
