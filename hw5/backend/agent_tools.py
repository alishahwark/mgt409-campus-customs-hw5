"""PydanticAI tools that delegate every shop fact lookup to MCP."""

from typing import Any

from pydantic_ai import RunContext

from .models import AgentName
from .runtime_types import AgentDependencies


async def delegate_to_agent(
    ctx: RunContext[AgentDependencies],
    target_agent: AgentName,
    task: str,
) -> dict[str, Any]:
    """Request bounded help from any other agent."""
    return await ctx.deps.runtime.delegate(
        source_agent=ctx.deps.agent_name,
        target_agent=target_agent,
        ticket_id=ctx.deps.ticket_id,
        task=task,
        depth=ctx.deps.context.delegation_depth + 1,
    )


async def mcp_get_open_tickets(ctx: RunContext[AgentDependencies]) -> dict[str, Any]:
    return await ctx.deps.runtime.mcp_tool(ctx.deps, "get_open_tickets", {})


async def mcp_get_ticket_details(
    ctx: RunContext[AgentDependencies], ticket_id: int
) -> dict[str, Any]:
    return await ctx.deps.runtime.mcp_tool(
        ctx.deps, "get_ticket_details", {"ticket_id": ticket_id}
    )


async def mcp_check_inventory_and_vendor(
    ctx: RunContext[AgentDependencies], sku: str, size: str
) -> dict[str, Any]:
    return await ctx.deps.runtime.mcp_tool(
        ctx.deps,
        "check_inventory_and_vendor",
        {"sku": sku, "size": size},
    )


async def mcp_check_cash_and_invoices(
    ctx: RunContext[AgentDependencies],
    invoice_id: int | None = None,
    ticket_id: int | None = None,
) -> dict[str, Any]:
    arguments = {
        key: value
        for key, value in {"invoice_id": invoice_id, "ticket_id": ticket_id}.items()
        if value is not None
    }
    return await ctx.deps.runtime.mcp_tool(
        ctx.deps, "check_cash_and_invoices", arguments
    )


async def mcp_check_lease_and_rent(
    ctx: RunContext[AgentDependencies],
    lease_id: int | None = None,
    ticket_id: int | None = None,
) -> dict[str, Any]:
    arguments = {
        key: value
        for key, value in {"lease_id": lease_id, "ticket_id": ticket_id}.items()
        if value is not None
    }
    return await ctx.deps.runtime.mcp_tool(
        ctx.deps, "check_lease_and_rent", arguments
    )


async def mcp_get_product_pricing(
    ctx: RunContext[AgentDependencies], sku: str
) -> dict[str, Any]:
    return await ctx.deps.runtime.mcp_tool(
        ctx.deps, "get_product_pricing", {"sku": sku}
    )


async def mcp_get_vendor_details(
    ctx: RunContext[AgentDependencies],
    vendor_id: int | None = None,
    sku: str | None = None,
    size: str | None = None,
) -> dict[str, Any]:
    arguments = {
        key: value
        for key, value in {
            "vendor_id": vendor_id,
            "sku": sku,
            "size": size,
        }.items()
        if value is not None
    }
    return await ctx.deps.runtime.mcp_tool(ctx.deps, "get_vendor_details", arguments)


async def mcp_get_cash_position(ctx: RunContext[AgentDependencies]) -> dict[str, Any]:
    return await ctx.deps.runtime.mcp_tool(ctx.deps, "get_cash_position", {})


async def mcp_get_payment_history(
    ctx: RunContext[AgentDependencies],
    invoice_id: int | None = None,
    lease_id: int | None = None,
) -> dict[str, Any]:
    arguments = {
        key: value
        for key, value in {"invoice_id": invoice_id, "lease_id": lease_id}.items()
        if value is not None
    }
    return await ctx.deps.runtime.mcp_tool(ctx.deps, "get_payment_history", arguments)


async def mcp_get_shop_date(ctx: RunContext[AgentDependencies]) -> dict[str, Any]:
    return await ctx.deps.runtime.mcp_tool(ctx.deps, "get_shop_date", {})


async def mcp_assess_ticket_resolution(
    ctx: RunContext[AgentDependencies], ticket_id: int
) -> dict[str, Any]:
    """Check completion evidence through MCP; never change a ticket status."""
    return await ctx.deps.runtime.mcp_tool(
        ctx.deps, "assess_ticket_resolution", {"ticket_id": ticket_id}
    )


ALL_AGENT_TOOLS = [
    delegate_to_agent,
    mcp_get_open_tickets,
    mcp_get_ticket_details,
    mcp_check_inventory_and_vendor,
    mcp_check_cash_and_invoices,
    mcp_check_lease_and_rent,
    mcp_get_product_pricing,
    mcp_get_vendor_details,
    mcp_get_cash_position,
    mcp_get_payment_history,
    mcp_get_shop_date,
    mcp_assess_ticket_resolution,
]
