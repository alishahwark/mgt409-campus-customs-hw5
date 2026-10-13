"""FastMCP tools for the Campus Customs working database.

Shop reads are exposed as read-only tools. Payment, rent-ticket closure, and
reset writes are separately gated and perform their own safety checks.
"""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import math
import os
from pathlib import Path
import shutil
import sqlite3
import threading
from typing import Any, Iterator

from mcp.server.fastmcp import FastMCP


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "campus_customs_new.db"
ORIGINAL_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "campus_customs.db"
DB_WRITE_LOCK = threading.Lock()
EXECUTED_APPROVAL_IDS: set[str] = set()

mcp = FastMCP("Campus Customs")


@contextmanager
def readonly_connection() -> Iterator[sqlite3.Connection]:
    """Open the working database in SQLite read-only mode."""
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def write_connection() -> Iterator[sqlite3.Connection]:
    """Open the working database for one transactional MCP-owned write."""
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else dict(row)


def database_error(exc: sqlite3.Error) -> dict[str, Any]:
    return {"ok": False, "error": f"Database error: {exc}"}


@mcp.tool(
    name="check_inventory_and_vendor",
    description=(
        "Read-only check for a product SKU and size. Use for Ticket 101 to "
        "compare requested quantity with inventory and identify a matching "
        "reprint vendor, lead time, and open invoice."
    ),
)
def check_inventory_and_vendor(sku: str, size: str) -> dict[str, Any]:
    """Check stock, the open customer-order quantity, and matching vendor data."""
    if not sku or not size:
        return {"ok": False, "error": "Both sku and size are required."}

    try:
        with readonly_connection() as connection:
            inventory_row = connection.execute(
                """
                SELECT sku, name, size, qty, location
                FROM inventory
                WHERE sku = ? AND size = ?
                """,
                (sku, size),
            ).fetchone()

            ticket_rows = connection.execute(
                """
                SELECT id, qty
                FROM tickets
                WHERE status = 'open'
                  AND sku = ?
                  AND size = ?
                ORDER BY id
                """,
                (sku, size),
            ).fetchall()
            requested_quantities = [
                int(row["qty"]) for row in ticket_rows if row["qty"] is not None
            ]
            requested_quantity = (
                sum(requested_quantities) if requested_quantities else None
            )

            linked_invoice_rows = connection.execute(
                """
                SELECT
                    i.id AS invoice_id,
                    i.vendor_id,
                    i.amount,
                    i.due_date,
                    i.status,
                    i.description,
                    v.id AS matched_vendor_id,
                    v.name AS vendor_name,
                    v.specialty,
                    v.lead_days
                FROM tickets AS t
                JOIN invoices AS i ON i.id = t.invoice_id
                JOIN vendors AS v ON v.id = i.vendor_id
                WHERE t.sku = ? AND t.size = ?
                ORDER BY i.id
                """,
                (sku, size),
            ).fetchall()

            linked_invoices = [dict(row) for row in linked_invoice_rows]
            vendor_candidates = {
                row["matched_vendor_id"]: {
                    "id": row["matched_vendor_id"],
                    "name": row["vendor_name"],
                    "specialty": row["specialty"],
                    "lead_days": row["lead_days"],
                }
                for row in linked_invoice_rows
                if row["matched_vendor_id"] is not None
            }

            vendor = None
            if len(vendor_candidates) == 1:
                vendor = next(iter(vendor_candidates.values()))
            open_unpaid_invoices = []
            if vendor is not None:
                open_unpaid_invoices = [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT id, vendor_id, amount, due_date, status, description
                        FROM invoices WHERE vendor_id = ? AND status = 'open'
                        ORDER BY id
                        """,
                        (vendor["id"],),
                    ).fetchall()
                ]

            stock = row_to_dict(inventory_row)
            if inventory_row is None:
                shortage = {
                    "is_short": None,
                    "quantity": None,
                    "explanation": "No inventory row exists for this SKU and size.",
                }
            elif requested_quantity is None:
                shortage = {
                    "is_short": None,
                    "quantity": None,
                    "explanation": (
                        "No open ticket was found for this SKU and size."
                    ),
                }
            else:
                shortage_quantity = max(
                    requested_quantity - int(inventory_row["qty"]),
                    0,
                )
                shortage = {
                    "is_short": shortage_quantity > 0,
                    "quantity": shortage_quantity,
                    "explanation": (
                        "Shortage is calculated from matching open ticket quantities "
                        "minus available inventory."
                    ),
                }

            if vendor is None:
                vendor_can_ship = None
                vendor_explanation = (
                    "No single matching vendor with a lead time was found; the schema "
                    "has no explicit shipping-capability field."
                )
                lead_time_days = None
            else:
                lead_time_days = vendor["lead_days"]
                vendor_can_ship = False if open_unpaid_invoices else None
                vendor_explanation = (
                    "An open unpaid invoice bars new shipments."
                    if open_unpaid_invoices else
                    "No open unpaid invoice remains, but supplier capacity, quote, "
                    "order acceptance, and shipment are not recorded."
                )

            return {
                "ok": True,
                "sku": sku,
                "size": size,
                "ticket_ids": [int(row["id"]) for row in ticket_rows],
                "requested_quantity": requested_quantity,
                "stock": stock,
                "shortage": shortage,
                "vendor": vendor,
                "linked_invoices": linked_invoices,
                "lead_time_days": lead_time_days,
                "vendor_can_ship": vendor_can_ship,
                "vendor_can_ship_explanation": vendor_explanation,
                "open_unpaid_invoices": open_unpaid_invoices,
            }
    except sqlite3.Error as exc:
        return database_error(exc)


@mcp.tool(
    name="check_cash_and_invoices",
    description=(
        "Read-only cash and invoice check for Ticket 102. Accept an invoice_id "
        "or ticket_id, inspect recorded payments and cash accounts, and never "
        "execute a payment or change a balance."
    ),
)
def check_cash_and_invoices(
    invoice_id: int | None = None,
    ticket_id: int | None = None,
) -> dict[str, Any]:
    """Return invoice, payment, and cash coverage information without writing."""
    if invoice_id is None and ticket_id is None:
        return {"ok": False, "error": "Provide invoice_id or ticket_id."}

    try:
        with readonly_connection() as connection:
            ticket = None
            resolved_invoice_id = invoice_id
            if ticket_id is not None:
                ticket = connection.execute(
                    """
                    SELECT id, type, status, invoice_id
                    FROM tickets
                    WHERE id = ?
                    """,
                    (ticket_id,),
                ).fetchone()
                if ticket is None:
                    return {"ok": False, "error": f"Ticket {ticket_id} was not found."}
                ticket_invoice_id = ticket["invoice_id"]
                if (
                    resolved_invoice_id is not None
                    and ticket_invoice_id is not None
                    and resolved_invoice_id != ticket_invoice_id
                ):
                    return {
                        "ok": False,
                        "error": "invoice_id does not match the ticket's invoice_id.",
                    }
                if resolved_invoice_id is None:
                    resolved_invoice_id = ticket_invoice_id

            cash_rows = connection.execute(
                """
                SELECT name, balance, date
                FROM cash_accounts
                ORDER BY name
                """
            ).fetchall()
            cash_accounts = [dict(row) for row in cash_rows]
            available_cash = sum(float(row["balance"]) for row in cash_rows)

            if resolved_invoice_id is None:
                return {
                    "ok": True,
                    "ticket_id": ticket_id,
                    "invoice_id": None,
                    "invoice": None,
                    "invoice_amount": None,
                    "payment_status": "no_invoice_reference",
                    "available_cash": available_cash,
                    "cash_accounts": cash_accounts,
                    "existing_payments": [],
                    "recorded_payment_total": 0.0,
                    "remaining_amount": None,
                    "sufficient_cash": None,
                    "explanation": (
                        "The referenced ticket has no invoice_id, so no invoice "
                        "payment can be inferred."
                    ),
                }

            invoice = connection.execute(
                """
                SELECT id, vendor_id, amount, due_date, status, description
                FROM invoices
                WHERE id = ?
                """,
                (resolved_invoice_id,),
            ).fetchone()
            if invoice is None:
                return {
                    "ok": False,
                    "error": f"Invoice {resolved_invoice_id} was not found.",
                }

            payment_rows = connection.execute(
                """
                SELECT id, kind, ref_id, amount, account, paid_at, approved_by
                FROM payments
                WHERE ref_id = ?
                ORDER BY id
                """,
                (resolved_invoice_id,),
            ).fetchall()
            existing_payments = [dict(row) for row in payment_rows]
            recorded_payment_total = sum(
                float(row["amount"]) for row in payment_rows
            )
            remaining_amount = max(
                float(invoice["amount"]) - recorded_payment_total,
                0.0,
            )

            return {
                "ok": True,
                "ticket_id": ticket_id,
                "invoice_id": int(invoice["id"]),
                "invoice": row_to_dict(invoice),
                "invoice_amount": float(invoice["amount"]),
                "payment_status": invoice["status"],
                "available_cash": available_cash,
                "cash_accounts": cash_accounts,
                "existing_payments": existing_payments,
                "recorded_payment_total": recorded_payment_total,
                "remaining_amount": remaining_amount,
                "sufficient_cash": available_cash >= remaining_amount,
                "explanation": (
                    "sufficient_cash compares available cash with the invoice amount "
                    "remaining after recorded payments; no payment was executed."
                ),
            }
    except sqlite3.Error as exc:
        return database_error(exc)


@mcp.tool(
    name="check_lease_and_rent",
    description=(
        "Read-only lease and rent check for Ticket 102 or a supplied lease_id. "
        "Use the desk table's date_today value and do not assume rent was paid."
    ),
)
def check_lease_and_rent(
    lease_id: int | None = None,
    ticket_id: int | None = None,
) -> dict[str, Any]:
    """Return lease, due-date, and recorded rent-payment information."""
    if lease_id is None and ticket_id is None:
        return {"ok": False, "error": "Provide lease_id or ticket_id."}

    try:
        with readonly_connection() as connection:
            ticket = None
            resolved_lease_id = lease_id
            if ticket_id is not None:
                ticket = connection.execute(
                    """
                    SELECT id, type, subject, status, lease_id, invoice_id
                    FROM tickets
                    WHERE id = ?
                    """,
                    (ticket_id,),
                ).fetchone()
                if ticket is None:
                    return {"ok": False, "error": f"Ticket {ticket_id} was not found."}
                ticket_lease_id = ticket["lease_id"]
                if (
                    resolved_lease_id is not None
                    and ticket_lease_id is not None
                    and resolved_lease_id != ticket_lease_id
                ):
                    return {
                        "ok": False,
                        "error": "lease_id does not match the ticket's lease_id.",
                    }
                if resolved_lease_id is None:
                    resolved_lease_id = ticket_lease_id

            desk = connection.execute(
                """
                SELECT date_today, notes
                FROM desk
                LIMIT 1
                """
            ).fetchone()
            current_date = desk["date_today"] if desk is not None else None

            if resolved_lease_id is None:
                return {
                    "ok": True,
                    "ticket_id": ticket_id,
                    "lease_id": None,
                    "lease": None,
                    "current_date": current_date,
                    "rent_amount": None,
                    "due_date": None,
                    "payment_status": "no_lease_reference",
                    "rent_overdue": None,
                    "relevant_payments": [],
                    "relevant_invoices": [],
                    "explanation": (
                        "The referenced ticket has no lease_id, so lease and rent "
                        "status cannot be inferred from the database."
                    ),
                }

            lease = connection.execute(
                """
                SELECT id, space_name, landlord, monthly_rent, next_due, notes
                FROM leases
                WHERE id = ?
                """,
                (resolved_lease_id,),
            ).fetchone()
            if lease is None:
                return {"ok": False, "error": f"Lease {resolved_lease_id} was not found."}

            payment_rows = connection.execute(
                """
                SELECT id, kind, ref_id, amount, account, paid_at, approved_by
                FROM payments
                WHERE ref_id = ?
                ORDER BY id
                """,
                (resolved_lease_id,),
            ).fetchall()
            relevant_payments = [dict(row) for row in payment_rows]

            relevant_invoices = []
            if ticket is not None and ticket["invoice_id"] is not None:
                invoice = connection.execute(
                    """
                    SELECT id, vendor_id, amount, due_date, status, description
                    FROM invoices
                    WHERE id = ?
                    """,
                    (ticket["invoice_id"],),
                ).fetchone()
                if invoice is not None:
                    relevant_invoices.append(dict(invoice))

            rent_amount = float(lease["monthly_rent"])
            recorded_payment_total = sum(
                float(row["amount"]) for row in payment_rows
            )
            if recorded_payment_total >= rent_amount and payment_rows:
                payment_status = "paid_by_recorded_payments"
            elif payment_rows:
                payment_status = "partially_paid_or_unconfirmed"
            else:
                payment_status = "unpaid_or_unconfirmed"

            rent_overdue = None
            date_explanation = None
            try:
                if current_date is not None:
                    rent_overdue = date.fromisoformat(current_date) > date.fromisoformat(
                        lease["next_due"]
                    )
            except ValueError:
                date_explanation = (
                    "Could not compare dates because desk.date_today or leases.next_due "
                    "is not ISO formatted."
                )

            result = {
                "ok": True,
                "ticket_id": ticket_id,
                "lease_id": int(lease["id"]),
                "lease": row_to_dict(lease),
                "current_date": current_date,
                "rent_amount": rent_amount,
                "due_date": lease["next_due"],
                "payment_status": payment_status,
                "rent_overdue": rent_overdue,
                "relevant_payments": relevant_payments,
                "relevant_invoices": relevant_invoices,
                "recorded_payment_total": recorded_payment_total,
                "explanation": (
                    "Payment status is based only on records returned from payments; "
                    "no payment is assumed."
                ),
            }
            if date_explanation is not None:
                result["date_explanation"] = date_explanation
            return result
    except sqlite3.Error as exc:
        return database_error(exc)


@mcp.tool(
    name="get_open_tickets",
    description="Read-only list of all open tickets and the current shop date for the Boss agent.",
)
def get_open_tickets() -> dict[str, Any]:
    """Return open tickets and desk.date_today."""
    try:
        with readonly_connection() as connection:
            tickets = connection.execute(
                """
                SELECT id, type, requester, subject, sku, size, qty, lease_id,
                       invoice_id, status, notes, created_at
                FROM tickets
                WHERE status = 'open'
                ORDER BY id
                """
            ).fetchall()
            desk = connection.execute(
                "SELECT date_today, notes FROM desk LIMIT 1"
            ).fetchone()
            return {
                "ok": True,
                "shop_date": desk["date_today"] if desk else None,
                "tickets": [dict(row) for row in tickets],
            }
    except sqlite3.Error as exc:
        return database_error(exc)


@mcp.tool(
    name="list_tickets",
    description="Read all working-database tickets, including resolved and dashboard-created tickets, for the desk UI.",
)
def list_tickets() -> dict[str, Any]:
    """List every ticket without changing its status or relationships."""
    try:
        with readonly_connection() as connection:
            rows = connection.execute(
                "SELECT id, type, requester, subject, sku, size, qty, lease_id, "
                "invoice_id, status, notes, created_at FROM tickets ORDER BY id"
            ).fetchall()
            resolutions: dict[int, dict[str, Any]] = {}
            if _table_exists(connection, "ticket_resolution_records"):
                resolutions = {
                    int(row["ticket_id"]): dict(row)
                    for row in connection.execute(
                        "SELECT ticket_id, decision, customer_draft, shop_date, "
                        "stock_at_decision, shortage_at_decision, communication_status, "
                        "fulfillment_status FROM ticket_resolution_records"
                    ).fetchall()
                }
            desk = connection.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
            return {
                "ok": True,
                "shop_date": desk["date_today"] if desk else None,
                "tickets": [dict(row) | {"resolution": resolutions.get(int(row["id"]))} for row in rows],
            }
    except sqlite3.Error as exc:
        return database_error(exc)


@mcp.tool(
    name="create_ticket",
    description=(
        "Create one open dashboard ticket in the working database from a required "
        "subject and description. SQLite assigns a unique ID; no SKU, vendor, "
        "invoice, lease, payment, or customer relationship is inferred."
    ),
)
def create_ticket(subject: str, description: str) -> dict[str, Any]:
    """Insert a minimal ticket atomically, using the shop date for created_at."""
    if not isinstance(subject, str) or not isinstance(description, str):
        return {"ok": False, "error": "Subject and description must be text."}
    subject = subject.strip()
    description = description.strip()
    if not subject or not description:
        return {"ok": False, "error": "Subject and description are required."}
    if len(subject) > 120 or len(description) > 2000 or "\x00" in subject + description:
        return {"ok": False, "error": "Subject or description is invalid or too long."}
    try:
        with DB_WRITE_LOCK:
            with write_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                desk = connection.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
                if desk is None or not desk["date_today"]:
                    return {"ok": False, "error": "The shop date is unavailable; ticket was not created."}
                cursor = connection.execute(
                    "INSERT INTO tickets (type, requester, subject, status, notes, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("dashboard_entry", "Not provided", subject, "open", description, desk["date_today"]),
                )
                ticket = connection.execute(
                    "SELECT id, type, requester, subject, sku, size, qty, lease_id, "
                    "invoice_id, status, notes, created_at FROM tickets WHERE id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
                return {"ok": True, "ticket": dict(ticket), "shop_date": desk["date_today"]}
    except sqlite3.Error as exc:
        return database_error(exc)


@mcp.tool(
    name="get_ticket_details",
    description=(
        "Read-only verified details for one ticket and any records linked by the "
        "actual nullable ticket fields."
    ),
)
def get_ticket_details(ticket_id: int) -> dict[str, Any]:
    """Return a ticket plus only records supported by its actual fields."""
    try:
        with readonly_connection() as connection:
            ticket = connection.execute(
                """
                SELECT id, type, requester, subject, sku, size, qty, lease_id,
                       invoice_id, status, notes, created_at
                FROM tickets
                WHERE id = ?
                """,
                (ticket_id,),
            ).fetchone()
            if ticket is None:
                return {"ok": False, "code": "not_found", "error": f"Ticket {ticket_id} was not found."}

            ticket_data = dict(ticket)
            inventory = None
            pricing = None
            if ticket["sku"] is not None and ticket["size"] is not None:
                inventory = row_to_dict(
                    connection.execute(
                        """
                        SELECT sku, name, size, qty, location
                        FROM inventory
                        WHERE sku = ? AND size = ?
                        """,
                        (ticket["sku"], ticket["size"]),
                    ).fetchone()
                )
            if ticket["sku"] is not None:
                pricing = row_to_dict(
                    connection.execute(
                        """
                        SELECT sku, unit_cost, list_price
                        FROM pricing
                        WHERE sku = ?
                        """,
                        (ticket["sku"],),
                    ).fetchone()
                )

            invoice = None
            vendor = None
            if ticket["invoice_id"] is not None:
                invoice_row = connection.execute(
                    """
                    SELECT id, vendor_id, amount, due_date, status, description
                    FROM invoices
                    WHERE id = ?
                    """,
                    (ticket["invoice_id"],),
                ).fetchone()
                invoice = row_to_dict(invoice_row)
                if invoice_row is not None:
                    vendor = row_to_dict(
                        connection.execute(
                            """
                            SELECT id, name, specialty, lead_days
                            FROM vendors
                            WHERE id = ?
                            """,
                            (invoice_row["vendor_id"],),
                        ).fetchone()
                    )

            lease = None
            if ticket["lease_id"] is not None:
                lease = row_to_dict(
                    connection.execute(
                        """
                        SELECT id, space_name, landlord, monthly_rent, next_due, notes
                        FROM leases
                        WHERE id = ?
                        """,
                        (ticket["lease_id"],),
                    ).fetchone()
                )

            reference_ids = [
                value
                for value in (ticket["invoice_id"], ticket["lease_id"])
                if value is not None
            ]
            payments = []
            if reference_ids:
                placeholders = ", ".join("?" for _ in reference_ids)
                payments = [
                    dict(row)
                    for row in connection.execute(
                        f"""
                        SELECT id, kind, ref_id, amount, account, paid_at, approved_by
                        FROM payments
                        WHERE ref_id IN ({placeholders})
                        ORDER BY id
                        """,
                        reference_ids,
                    ).fetchall()
                ]

            desk = connection.execute(
                "SELECT date_today FROM desk LIMIT 1"
            ).fetchone()
            resolution = None
            if _table_exists(connection, "ticket_resolution_records"):
                resolution = row_to_dict(connection.execute(
                    "SELECT ticket_id, decision, customer_draft, shop_date, "
                    "stock_at_decision, shortage_at_decision, communication_status, "
                    "fulfillment_status FROM ticket_resolution_records WHERE ticket_id = ?",
                    (ticket_id,),
                ).fetchone())
            return {
                "ok": True,
                "ticket": ticket_data,
                "shop_date": desk["date_today"] if desk else None,
                "inventory": inventory,
                "pricing": pricing,
                "invoice": invoice,
                "vendor": vendor,
                "lease": lease,
                "payments": payments,
                "resolution": resolution,
                "relationship_note": (
                    "Only non-null ticket invoice_id and lease_id values are treated "
                    "as declared links; SKU, size, and payment ref_id matches are "
                    "reported as value-based records."
                ),
            }
    except sqlite3.Error as exc:
        return database_error(exc)


@mcp.tool(
    name="get_product_pricing",
    description="Read-only lookup of actual SKU pricing, cost, and calculated margin.",
)
def get_product_pricing(sku: str) -> dict[str, Any]:
    """Return pricing and a derived margin for one SKU."""
    if not sku:
        return {"ok": False, "error": "sku is required."}
    try:
        with readonly_connection() as connection:
            row = connection.execute(
                """
                SELECT sku, unit_cost, list_price
                FROM pricing
                WHERE sku = ?
                """,
                (sku,),
            ).fetchone()
            if row is None:
                return {"ok": True, "sku": sku, "pricing": None, "margin": None}
            data = dict(row)
            margin = float(row["list_price"]) - float(row["unit_cost"])
            margin_rate = (
                margin / float(row["list_price"])
                if float(row["list_price"]) != 0
                else None
            )
            return {
                "ok": True,
                "sku": sku,
                "pricing": data,
                "margin": margin,
                "margin_rate": margin_rate,
            }
    except sqlite3.Error as exc:
        return database_error(exc)


@mcp.tool(
    name="get_vendor_details",
    description=(
        "Read-only vendor and open-invoice lookup by vendor_id or product SKU/size. "
        "Reports an explicit restriction when open invoices exist."
    ),
)
def get_vendor_details(
    vendor_id: int | None = None,
    sku: str | None = None,
    size: str | None = None,
) -> dict[str, Any]:
    """Return vendors, open invoices, lead times, and payment restrictions."""
    if vendor_id is None and not sku:
        return {"ok": False, "error": "Provide vendor_id or sku."}
    try:
        with readonly_connection() as connection:
            if vendor_id is not None:
                vendor_rows = connection.execute(
                    """
                    SELECT id, name, specialty, lead_days
                    FROM vendors
                    WHERE id = ?
                    """,
                    (vendor_id,),
                ).fetchall()
                invoice_rows = connection.execute(
                    """
                    SELECT id, vendor_id, amount, due_date, status, description
                    FROM invoices
                    WHERE vendor_id = ? AND status = 'open'
                    ORDER BY id
                    """,
                    (vendor_id,),
                ).fetchall()
            else:
                vendor_query = """
                    SELECT DISTINCT v.id, v.name, v.specialty, v.lead_days
                    FROM tickets AS t
                    JOIN invoices AS i ON i.id = t.invoice_id
                    JOIN vendors AS v ON v.id = i.vendor_id
                    WHERE t.sku = ?
                """
                params: list[Any] = [sku]
                if size:
                    vendor_query += " AND t.size = ?"
                    params.append(size)
                vendor_rows = connection.execute(vendor_query, params).fetchall()
                vendor_ids = [row["id"] for row in vendor_rows]
                invoice_rows = []
                if vendor_ids:
                    placeholders = ", ".join("?" for _ in vendor_ids)
                    invoice_rows = connection.execute(
                        f"SELECT id, vendor_id, amount, due_date, status, description "
                        f"FROM invoices WHERE status = 'open' AND vendor_id IN ({placeholders}) ORDER BY id",
                        vendor_ids,
                    ).fetchall()

            vendors = [dict(row) for row in vendor_rows]
            open_invoices = [dict(row) for row in invoice_rows]
            restricted = bool(open_invoices)
            return {
                "ok": True,
                "vendors": vendors,
                "open_unpaid_invoices": open_invoices,
                "can_ship_new_products": False if restricted else None,
                "shipping_restriction": (
                    "Vendor has an open unpaid invoice; no new shipment may be proposed."
                    if restricted
                    else "No vendor is linked to this SKU/size in the ticket invoice records."
                    if not vendors
                    else "No open unpaid invoice was found; supplier capacity, quote, order acceptance, and shipment are not recorded."
                ),
            }
    except sqlite3.Error as exc:
        return database_error(exc)


@mcp.tool(
    name="get_cash_position",
    description="Read-only cash, payment, and open-obligation summary for affordability checks.",
)
def get_cash_position() -> dict[str, Any]:
    """Return current cash accounts, payments, and open invoice obligations."""
    try:
        with readonly_connection() as connection:
            accounts = [
                dict(row)
                for row in connection.execute(
                    "SELECT name, balance, date FROM cash_accounts ORDER BY name"
                ).fetchall()
            ]
            payments = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT id, kind, ref_id, amount, account, paid_at, approved_by
                    FROM payments
                    ORDER BY id
                    """
                ).fetchall()
            ]
            open_invoices = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT id, vendor_id, amount, due_date, status, description
                    FROM invoices
                    WHERE status = 'open'
                    ORDER BY id
                    """
                ).fetchall()
            ]
            return {
                "ok": True,
                "available_cash": sum(float(row["balance"]) for row in accounts),
                "cash_accounts": accounts,
                "existing_payments": payments,
                "open_invoice_obligations": open_invoices,
                "open_invoice_total": sum(
                    float(row["amount"]) for row in open_invoices
                ),
            }
    except sqlite3.Error as exc:
        return database_error(exc)


@mcp.tool(
    name="get_payment_history",
    description="Read-only payment history for an invoice or lease reference, with invoice status when available.",
)
def get_payment_history(
    invoice_id: int | None = None,
    lease_id: int | None = None,
) -> dict[str, Any]:
    """Return recorded payments without creating or changing any payment."""
    if invoice_id is None and lease_id is None:
        return {"ok": False, "error": "Provide invoice_id or lease_id."}
    reference_id = invoice_id if invoice_id is not None else lease_id
    try:
        with readonly_connection() as connection:
            payments = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT id, kind, ref_id, amount, account, paid_at, approved_by
                    FROM payments
                    WHERE ref_id = ?
                    ORDER BY id
                    """,
                    (reference_id,),
                ).fetchall()
            ]
            invoice = None
            if invoice_id is not None:
                invoice = row_to_dict(
                    connection.execute(
                        """
                        SELECT id, vendor_id, amount, due_date, status, description
                        FROM invoices
                        WHERE id = ?
                        """,
                        (invoice_id,),
                    ).fetchone()
                )
            return {
                "ok": True,
                "reference_id": reference_id,
                "reference_kind": "invoice" if invoice_id is not None else "lease",
                "invoice": invoice,
                "payments": payments,
                "recorded_payment_total": sum(
                    float(row["amount"]) for row in payments
                ),
                "payment_status": (
                    invoice["status"]
                    if invoice is not None
                    else "paid_records_unconfirmed"
                    if payments
                    else "no_recorded_payments"
                ),
            }
    except sqlite3.Error as exc:
        return database_error(exc)


@mcp.tool(
    name="get_shop_date",
    description="Read-only lookup of desk.date_today for all overdue calculations.",
)
def get_shop_date() -> dict[str, Any]:
    """Return the shop date from desk, never the system date."""
    try:
        with readonly_connection() as connection:
            desk = connection.execute(
                "SELECT date_today, notes FROM desk LIMIT 1"
            ).fetchone()
            return {
                "ok": True,
                "date_today": desk["date_today"] if desk else None,
                "notes": desk["notes"] if desk else None,
            }
    except sqlite3.Error as exc:
        return database_error(exc)


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


@mcp.tool(
    name="assess_ticket_resolution",
    description=(
        "Read-only check for Tickets 101 and 103: live stock, pricing, linked "
        "invoice, and any recorded internal desk decision/draft. A resolved desk "
        "ticket does not imply fulfillment, supplier acceptance, or sent email."
    ),
)
def assess_ticket_resolution(ticket_id: int) -> dict[str, Any]:
    """Distinguish internal desk completion from physical and external events."""
    if ticket_id not in {101, 103}:
        return {"ok": False, "error": "Only Tickets 101 and 103 are supported."}
    try:
        with readonly_connection() as connection:
            ticket = connection.execute(
                "SELECT id, type, status, sku, size, qty, invoice_id FROM tickets WHERE id = ?",
                (ticket_id,),
            ).fetchone()
            if ticket is None:
                return {"ok": False, "error": f"Ticket {ticket_id} was not found."}
            stock = connection.execute(
                "SELECT qty FROM inventory WHERE sku = ? AND size = ?",
                (ticket["sku"], ticket["size"]),
            ).fetchone()
            pricing = connection.execute(
                "SELECT unit_cost, list_price FROM pricing WHERE sku = ?",
                (ticket["sku"],),
            ).fetchone()
            invoice = None
            if ticket["invoice_id"] is not None:
                invoice = connection.execute(
                    "SELECT id, vendor_id, status, amount FROM invoices WHERE id = ?",
                    (ticket["invoice_id"],),
                ).fetchone()
            request = None
            if _table_exists(connection, "replenishment_review_requests"):
                request = connection.execute(
                    "SELECT id, ticket_id, sku, size, qty, vendor_id, status, shop_date "
                    "FROM replenishment_review_requests WHERE ticket_id = ?",
                    (ticket_id,),
                ).fetchone()
            resolution = None
            if _table_exists(connection, "ticket_resolution_records"):
                resolution = connection.execute(
                    "SELECT ticket_id, decision, customer_draft, boss_reasoning, "
                    "shop_date, stock_at_decision, shortage_at_decision, "
                    "communication_status, fulfillment_status "
                    "FROM ticket_resolution_records WHERE ticket_id = ?",
                    (ticket_id,),
                ).fetchone()
            available = stock["qty"] if stock is not None else None
            requested = ticket["qty"]
            shortage = max(int(requested) - int(available), 0) if requested is not None and available is not None else None
            missing = []
            if ticket_id == 101 and request is None:
                missing.append("No internal replenishment review request is recorded.")
            if resolution is None:
                missing.append("No final internal decision and complete unsent customer draft are recorded.")
            elif (
                resolution["decision"] != (
                    "unavailable_request_alternative" if ticket_id == 101
                    else "decline_unfulfillable_bulk_request"
                )
                or resolution["communication_status"] != "unsent_draft"
                or resolution["fulfillment_status"] != "not_fulfilled"
                or not resolution["customer_draft"]
            ):
                missing.append("Recorded decision or draft status is inconsistent with this ticket.")
            if ticket["status"] != "resolved" and resolution is not None:
                missing.append("Resolution record and ticket status disagree.")
            return {
                "ok": True,
                "ticket_id": ticket_id,
                "ticket_status": ticket["status"],
                "ticket_type": ticket["type"],
                "sku": ticket["sku"],
                "size": ticket["size"],
                "requested_quantity": requested,
                "available_quantity": available,
                "shortage_quantity": shortage,
                "pricing": row_to_dict(pricing),
                "linked_invoice": row_to_dict(invoice),
                "replenishment_review_request": row_to_dict(request),
                "resolution_record": row_to_dict(resolution),
                "can_close": not missing and ticket["status"] == "resolved",
                "missing_evidence": missing,
                "explanation": (
                    "This assesses the simulated internal desk workflow only. A resolved "
                    "ticket does not mean goods were sourced, purchased, shipped, received, "
                    "delivered, or that a customer message was sent or accepted."
                ),
            }
    except sqlite3.Error as exc:
        return database_error(exc)


@mcp.tool(
    name="record_replenishment_review_request",
    description=(
        "Idempotently record a Ticket 101 internal review request for its verified "
        "one-unit shortage and linked vendor. No purchase order, vendor contact, "
        "shipment, payment, or inventory change occurs."
    ),
)
def record_replenishment_review_request(ticket_id: int) -> dict[str, Any]:
    """Create an administrative follow-up, never a vendor commitment."""
    if ticket_id != 101:
        return {"ok": False, "error": "Only Ticket 101 is supported."}
    with DB_WRITE_LOCK:
        try:
            with write_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                ticket = connection.execute(
                    "SELECT id, type, status, sku, size, qty, invoice_id FROM tickets WHERE id = ?",
                    (ticket_id,),
                ).fetchone()
                if ticket is None or ticket["type"] != "customer_order" or ticket["status"] != "open":
                    return {"ok": False, "error": "Ticket 101 must be an open customer order."}
                stock = connection.execute(
                    "SELECT qty FROM inventory WHERE sku = ? AND size = ?",
                    (ticket["sku"], ticket["size"]),
                ).fetchone()
                if stock is None or ticket["qty"] is None:
                    return {"ok": False, "error": "Requested item or quantity is missing."}
                shortage = int(ticket["qty"]) - int(stock["qty"])
                if shortage <= 0:
                    return {"ok": False, "error": "There is no current shortage to review."}
                invoice = connection.execute(
                    "SELECT id, vendor_id, amount, status FROM invoices WHERE id = ?",
                    (ticket["invoice_id"],),
                ).fetchone()
                if invoice is None or invoice["status"] != "paid":
                    return {"ok": False, "error": "The ticket-linked vendor invoice is not paid."}
                vendor = connection.execute(
                    "SELECT id, name, lead_days FROM vendors WHERE id = ?",
                    (invoice["vendor_id"],),
                ).fetchone()
                if vendor is None or vendor["lead_days"] < 0:
                    return {"ok": False, "error": "Linked vendor or lead time is missing."}
                open_count = connection.execute(
                    "SELECT COUNT(*) FROM invoices WHERE vendor_id = ? AND status = 'open'",
                    (vendor["id"],),
                ).fetchone()[0]
                if open_count:
                    return {"ok": False, "error": "Vendor has open unpaid invoices."}
                paid = connection.execute(
                    "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE kind = 'invoice' AND ref_id = ?",
                    (invoice["id"],),
                ).fetchone()[0]
                if Decimal(str(paid)) != Decimal(str(invoice["amount"])):
                    return {"ok": False, "error": "Invoice payment record does not cover the linked bill."}
                desk = connection.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
                if desk is None or not desk["date_today"]:
                    return {"ok": False, "error": "Shop date is unavailable."}
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS replenishment_review_requests (
                        id INTEGER PRIMARY KEY,
                        ticket_id INTEGER NOT NULL UNIQUE REFERENCES tickets(id),
                        sku TEXT NOT NULL, size TEXT NOT NULL, qty INTEGER NOT NULL CHECK(qty > 0),
                        vendor_id INTEGER NOT NULL REFERENCES vendors(id),
                        status TEXT NOT NULL CHECK(status = 'internal_review_only'),
                        shop_date TEXT NOT NULL
                    )"""
                )
                existing = connection.execute(
                    "SELECT * FROM replenishment_review_requests WHERE ticket_id = ?", (ticket_id,)
                ).fetchone()
                if existing is not None:
                    if (existing["sku"], existing["size"], existing["qty"], existing["vendor_id"]) != (
                        ticket["sku"], ticket["size"], shortage, vendor["id"]
                    ):
                        return {"ok": False, "error": "Existing review request conflicts with current verified facts."}
                    changed = False
                    request = existing
                else:
                    cursor = connection.execute(
                        "INSERT INTO replenishment_review_requests "
                        "(ticket_id, sku, size, qty, vendor_id, status, shop_date) "
                        "VALUES (?, ?, ?, ?, ?, 'internal_review_only', ?)",
                        (ticket_id, ticket["sku"], ticket["size"], shortage, vendor["id"], desk["date_today"]),
                    )
                    request = connection.execute(
                        "SELECT * FROM replenishment_review_requests WHERE id = ?", (cursor.lastrowid,)
                    ).fetchone()
                    changed = True
                return {
                    "ok": True, "changed": changed, "request": dict(request),
                    "vendor_name": vendor["name"], "vendor_lead_days": vendor["lead_days"],
                    "meaning": "Internal review only; no vendor order, quote, shipment, stock receipt, or payment.",
                }
        except sqlite3.Error as exc:
            return database_error(exc)


@mcp.tool(
    name="close_operational_ticket",
    description=(
        "Atomically record a verified final internal desk decision and an unsent "
        "Customer Service draft for Ticket 101 or 103, then close only the desk "
        "ticket. Refuses unsupported decisions and does not change inventory or cash."
    ),
)
def close_operational_ticket(
    ticket_id: int,
    decision: str,
    customer_draft: str,
    boss_reasoning: str,
) -> dict[str, Any]:
    """Close a simulated desk task, not a physical order or customer contact."""
    expected = {
        101: "unavailable_request_alternative",
        103: "decline_unfulfillable_bulk_request",
    }
    if ticket_id not in expected or decision != expected[ticket_id]:
        return {"ok": False, "error": "Unsupported ticket or final decision."}
    draft = customer_draft.strip()
    reasoning = boss_reasoning.strip()
    if not 50 <= len(draft) <= 3000 or not 20 <= len(reasoning) <= 1500:
        return {"ok": False, "error": "A complete bounded draft and Boss reasoning are required."}
    lowered = draft.casefold().replace("’", "'")
    if any(phrase in lowered for phrase in ("will deliver", "confirmed delivery", "order confirmed", "discount approved", "guaranteed")):
        return {"ok": False, "error": "Draft contains an unverified commitment."}
    if ticket_id == 101 and not (
        ("out of stock" in lowered or "unavailable" in lowered)
        and ("alternative" in lowered or "another size" in lowered or "another style" in lowered)
        and ("size s" in lowered or "size-s" in lowered)
    ):
        return {"ok": False, "error": "Ticket 101 draft must accurately disclose size-S unavailability and ask about alternatives."}
    if ticket_id == 103 and not (
        "8" in lowered and "20" in lowered
        and "discount" in lowered
        and ("cannot offer" in lowered or "unable to offer" in lowered or "can't offer" in lowered)
    ):
        return {"ok": False, "error": "Ticket 103 draft must disclose stock, shortage, and the decision not to offer the requested quantity/discount."}

    with DB_WRITE_LOCK:
        try:
            with write_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                ticket = connection.execute(
                    "SELECT id, type, status, sku, size, qty, invoice_id FROM tickets WHERE id = ?",
                    (ticket_id,),
                ).fetchone()
                if ticket is None or ticket["status"] != "open":
                    return {"ok": False, "error": "Ticket is missing or is not open; duplicate closure refused."}
                wanted_type = "customer_order" if ticket_id == 101 else "price_override"
                if ticket["type"] != wanted_type or ticket["qty"] is None:
                    return {"ok": False, "error": "Ticket type or requested quantity does not match this decision."}
                inventory = connection.execute(
                    "SELECT qty FROM inventory WHERE sku = ? AND size = ?",
                    (ticket["sku"], ticket["size"]),
                ).fetchone()
                if inventory is None:
                    return {"ok": False, "error": "Requested SKU/size has no inventory row."}
                available = int(inventory["qty"])
                shortage = int(ticket["qty"]) - available
                if shortage <= 0:
                    return {"ok": False, "error": "The requested quantity is in stock; this unavailability decision is unsupported."}
                if ticket_id == 101:
                    if not _table_exists(connection, "replenishment_review_requests"):
                        return {"ok": False, "error": "Internal replenishment review request is missing."}
                    request = connection.execute(
                        "SELECT qty, sku, size, vendor_id, status FROM replenishment_review_requests WHERE ticket_id = ?",
                        (ticket_id,),
                    ).fetchone()
                    if request is None or request["status"] != "internal_review_only" or (
                        request["qty"], request["sku"], request["size"]
                    ) != (shortage, ticket["sku"], ticket["size"]):
                        return {"ok": False, "error": "Internal review request is missing or inconsistent."}
                    invoice = connection.execute(
                        "SELECT vendor_id, status FROM invoices WHERE id = ?", (ticket["invoice_id"],)
                    ).fetchone()
                    if invoice is None or invoice["status"] != "paid" or invoice["vendor_id"] != request["vendor_id"]:
                        return {"ok": False, "error": "Linked paid vendor invoice no longer matches the review request."}
                    if connection.execute(
                        "SELECT COUNT(*) FROM invoices WHERE vendor_id = ? AND status = 'open'",
                        (request["vendor_id"],),
                    ).fetchone()[0]:
                        return {"ok": False, "error": "Vendor has an open unpaid invoice."}
                    pricing = None
                else:
                    pricing = connection.execute(
                        "SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (ticket["sku"],)
                    ).fetchone()
                    if pricing is None or pricing["unit_cost"] < 0 or pricing["list_price"] <= 0:
                        return {"ok": False, "error": "Verified pricing is required for the bulk decision."}
                    if ticket["invoice_id"] is not None:
                        return {"ok": False, "error": "Unexpected linked supplier invoice requires review."}
                desk = connection.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
                if desk is None or not desk["date_today"]:
                    return {"ok": False, "error": "Shop date is unavailable."}
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS ticket_resolution_records (
                        ticket_id INTEGER PRIMARY KEY REFERENCES tickets(id),
                        decision TEXT NOT NULL,
                        customer_draft TEXT NOT NULL,
                        boss_reasoning TEXT NOT NULL,
                        shop_date TEXT NOT NULL,
                        stock_at_decision INTEGER NOT NULL,
                        shortage_at_decision INTEGER NOT NULL,
                        communication_status TEXT NOT NULL CHECK(communication_status = 'unsent_draft'),
                        fulfillment_status TEXT NOT NULL CHECK(fulfillment_status = 'not_fulfilled')
                    )"""
                )
                connection.execute(
                    "INSERT INTO ticket_resolution_records "
                    "(ticket_id, decision, customer_draft, boss_reasoning, shop_date, "
                    "stock_at_decision, shortage_at_decision, communication_status, fulfillment_status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'unsent_draft', 'not_fulfilled')",
                    (ticket_id, decision, draft, reasoning, desk["date_today"], available, shortage),
                )
                cursor = connection.execute(
                    "UPDATE tickets SET status = 'resolved' WHERE id = ? AND status = 'open'", (ticket_id,)
                )
                if cursor.rowcount != 1:
                    raise sqlite3.IntegrityError("Ticket changed before conditional closure.")
                return {
                    "ok": True, "changed": True, "ticket_id": ticket_id,
                    "status": "resolved", "decision": decision,
                    "stock_at_decision": available, "shortage_at_decision": shortage,
                    "communication_status": "unsent_draft", "fulfillment_status": "not_fulfilled",
                    "shop_date": desk["date_today"],
                    "meaning": "Only the simulated internal desk workflow is resolved; no customer contact or physical fulfillment occurred.",
                }
        except sqlite3.Error as exc:
            return database_error(exc)


@mcp.tool(
    name="execute_approved_payment",
    description=(
        "Approval-gated atomic payment tool. It rechecks the working database, "
        "cash, recorded payments, dates, and invoice or lease status before "
        "writing one approved invoice or rent payment. It never accepts an agent "
        "identity as approval and never permits a negative cash balance."
    ),
)
def execute_approved_payment(
    approval_id: str,
    human_approved_by: str,
    kind: str,
    reference_id: int,
    amount: float,
    account: str = "checking",
) -> dict[str, Any]:
    """Atomically apply one human-approved invoice or rent payment."""
    actor = human_approved_by.strip()
    if not approval_id.strip():
        return {"ok": False, "error": "approval_id is required."}
    if not actor:
        return {"ok": False, "error": "human_approved_by is required."}
    normalized_actor = actor.casefold().replace("-", "_").replace(" ", "_")
    forbidden_actors = {
        "agent",
        "boss",
        "inventory",
        "accounting",
        "facilities",
        "customer_service",
        "assistant",
        "system",
    }
    if normalized_actor in forbidden_actors or normalized_actor.startswith("agent_"):
        return {"ok": False, "error": "An agent or system identity cannot approve a payment."}
    if kind not in {"invoice", "rent"}:
        return {
            "ok": False,
            "error": "Only invoice and rent payments have matching tables in the actual schema.",
        }
    if reference_id < 1:
        return {"ok": False, "error": "reference_id must be positive."}
    if not math.isfinite(float(amount)) or float(amount) <= 0:
        return {"ok": False, "error": "amount must be a finite positive number."}

    with DB_WRITE_LOCK:
        if approval_id in EXECUTED_APPROVAL_IDS:
            return {"ok": False, "error": "This approval has already been executed."}
        try:
            with write_connection() as connection:
                account_row = connection.execute(
                    "SELECT name, balance, date FROM cash_accounts WHERE name = ?",
                    (account,),
                ).fetchone()
                if account_row is None:
                    return {"ok": False, "error": f"Cash account {account!r} was not found."}

                desk_row = connection.execute(
                    "SELECT date_today FROM desk LIMIT 1"
                ).fetchone()
                if desk_row is None or not desk_row["date_today"]:
                    return {"ok": False, "error": "desk.date_today is unavailable."}
                shop_date = str(desk_row["date_today"])

                reference_amount: float
                reference_status: str | None = None
                if kind == "invoice":
                    invoice = connection.execute(
                        """
                        SELECT id, vendor_id, amount, status
                        FROM invoices
                        WHERE id = ?
                        """,
                        (reference_id,),
                    ).fetchone()
                    if invoice is None:
                        return {"ok": False, "error": f"Invoice {reference_id} was not found."}
                    reference_amount = float(invoice["amount"])
                    reference_status = str(invoice["status"])
                    if reference_status == "paid":
                        return {"ok": False, "error": "The invoice is already marked paid."}
                else:
                    lease = connection.execute(
                        "SELECT id, monthly_rent FROM leases WHERE id = ?",
                        (reference_id,),
                    ).fetchone()
                    if lease is None:
                        return {"ok": False, "error": f"Lease {reference_id} was not found."}
                    reference_amount = float(lease["monthly_rent"])

                payment_total_row = connection.execute(
                    """
                    SELECT COALESCE(SUM(amount), 0) AS total
                    FROM payments
                    WHERE ref_id = ? AND kind = ?
                    """,
                    (reference_id, kind),
                ).fetchone()
                recorded_total = float(payment_total_row["total"])
                remaining_amount = max(reference_amount - recorded_total, 0.0)
                requested_amount = float(amount)
                if remaining_amount <= 0:
                    return {"ok": False, "error": "The referenced obligation is already fully paid."}
                if requested_amount > remaining_amount + 1e-9:
                    return {
                        "ok": False,
                        "error": "Payment exceeds the remaining recorded obligation.",
                        "remaining_amount": remaining_amount,
                    }

                balance = float(account_row["balance"])
                if requested_amount > balance + 1e-9:
                    return {
                        "ok": False,
                        "error": "Payment exceeds available cash.",
                        "available_cash": balance,
                        "required_amount": requested_amount,
                    }
                new_balance = balance - requested_amount
                if new_balance < -1e-9:
                    return {"ok": False, "error": "Payment would create a negative cash balance."}

                cursor = connection.execute(
                    """
                    INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (kind, reference_id, requested_amount, account, shop_date, actor),
                )
                connection.execute(
                    "UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?",
                    (max(new_balance, 0.0), shop_date, account),
                )

                new_reference_total = recorded_total + requested_amount
                new_status = reference_status
                if kind == "invoice" and new_reference_total >= reference_amount - 1e-9:
                    new_status = "paid"
                    connection.execute(
                        "UPDATE invoices SET status = 'paid' WHERE id = ?",
                        (reference_id,),
                    )

                result = {
                    "ok": True,
                    "approval_id": approval_id,
                    "payment_id": int(cursor.lastrowid),
                    "kind": kind,
                    "reference_id": reference_id,
                    "amount": requested_amount,
                    "account": account,
                    "approved_by": actor,
                    "paid_at": shop_date,
                    "new_balance": max(new_balance, 0.0),
                    "recorded_payment_total": new_reference_total,
                    "remaining_amount": max(reference_amount - new_reference_total, 0.0),
                    "reference_status": new_status,
                }
            EXECUTED_APPROVAL_IDS.add(approval_id)
            return result
        except sqlite3.Error as exc:
            return database_error(exc)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": f"Invalid payment input: {exc}"}


@mcp.tool(
    name="resolve_paid_rent_ticket",
    description=(
        "Close Ticket 102 only after the working database confirms its declared "
        "lease link, matching landlord, and human-approved rent payments covering "
        "the full monthly obligation. Never creates a payment."
    ),
)
def resolve_paid_rent_ticket(ticket_id: int) -> dict[str, Any]:
    """Atomically mark the paid rent notice resolved only on verified evidence."""
    if ticket_id != 102:
        return {"ok": False, "error": "Only Ticket 102's rent notice is supported."}
    with DB_WRITE_LOCK:
        try:
            with write_connection() as connection:
                ticket = connection.execute(
                    "SELECT id, type, requester, lease_id, invoice_id, status FROM tickets WHERE id = ?",
                    (ticket_id,),
                ).fetchone()
                if ticket is None or ticket["type"] != "rent_notice" or ticket["lease_id"] is None:
                    return {"ok": False, "error": "Ticket is not a declared rent notice with a lease link."}
                if ticket["invoice_id"] is not None:
                    return {"ok": False, "error": "Unexpected invoice link; rent relationship needs review."}
                lease = connection.execute(
                    "SELECT id, landlord, monthly_rent, next_due FROM leases WHERE id = ?",
                    (ticket["lease_id"],),
                ).fetchone()
                if lease is None or ticket["requester"] != lease["landlord"]:
                    return {"ok": False, "error": "Linked lease or landlord does not match the ticket."}
                desk = connection.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
                if desk is None or not desk["date_today"]:
                    return {"ok": False, "error": "Shop date is unavailable."}
                payments = connection.execute(
                    "SELECT id, amount, paid_at, approved_by FROM payments WHERE kind = ? AND ref_id = ? ORDER BY id",
                    ("rent", ticket["lease_id"]),
                ).fetchall()
                if not payments or any(not row["approved_by"] or row["paid_at"] > desk["date_today"] for row in payments):
                    return {"ok": False, "error": "No valid human-approved rent payment is recorded for this lease."}
                paid = sum((Decimal(str(row["amount"])) for row in payments), Decimal("0"))
                rent = Decimal(str(lease["monthly_rent"]))
                if paid != rent:
                    return {"ok": False, "error": "Recorded rent payments do not exactly cover the lease obligation.",
                            "recorded_payment_total": str(paid), "rent_amount": str(rent)}
                if ticket["status"] == "resolved":
                    return {"ok": True, "changed": False, "ticket_id": ticket_id, "status": "resolved"}
                if ticket["status"] != "open":
                    return {"ok": False, "error": f"Unexpected ticket status: {ticket['status']}"}
                cursor = connection.execute(
                    "UPDATE tickets SET status = 'resolved' WHERE id = ? AND status = 'open'",
                    (ticket_id,),
                )
                if cursor.rowcount != 1:
                    return {"ok": False, "error": "Ticket status changed concurrently."}
                return {
                    "ok": True, "changed": True, "ticket_id": ticket_id, "status": "resolved",
                    "lease_id": int(lease["id"]), "landlord": lease["landlord"],
                    "rent_amount": str(rent), "recorded_payment_total": str(paid),
                    "due_date": lease["next_due"], "shop_date": desk["date_today"],
                    "payment_ids": [int(row["id"]) for row in payments],
                }
        except sqlite3.Error as exc:
            return database_error(exc)


@mcp.tool(
    name="reset_working_database",
    description=(
        "Explicitly restore data/campus_customs_new.db from the untouched original "
        "database. Requires confirm=true and performs no reset automatically."
    ),
)
def reset_working_database(confirm: bool = False) -> dict[str, Any]:
    """Restore the working copy without ever modifying the original database."""
    if confirm is not True:
        return {"ok": False, "error": "Explicit confirm=true is required for a reset."}
    if not ORIGINAL_DB_PATH.is_file():
        return {"ok": False, "error": "The original database was not found."}

    temp_path = DB_PATH.with_name(DB_PATH.name + ".reset.tmp")
    with DB_WRITE_LOCK:
        try:
            shutil.copy2(ORIGINAL_DB_PATH, temp_path)
            with sqlite3.connect(temp_path) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                return {"ok": False, "error": f"Reset copy failed integrity check: {integrity}"}
            os.replace(temp_path, DB_PATH)
            EXECUTED_APPROVAL_IDS.clear()
            return {
                "ok": True,
                "reset": True,
                "database": "data/campus_customs_new.db",
                "source": "data/campus_customs.db",
            }
        except (OSError, sqlite3.Error) as exc:
            return {"ok": False, "error": f"Database reset failed: {exc}"}
        finally:
            if temp_path.exists():
                temp_path.unlink()


if __name__ == "__main__":
    mcp.run()
