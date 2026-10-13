"""MCP client used by agents; it contains no shop SQL."""

from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClientError(RuntimeError):
    """Raised when the configured MCP server cannot answer a tool call."""


class MCPToolClient:
    """Connect to the project-local MCP server over stdio."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self.tool_names: set[str] = set()

    async def __aenter__(self) -> "MCPToolClient":
        config_path = self.project_root / ".mcp.json"
        config = json.loads(config_path.read_text())
        server_config = config["mcpServers"]["campus-customs"]
        command = Path(server_config["command"])
        if command.is_absolute():
            raise MCPClientError(".mcp.json must use a relative command path")
        executable = self.project_root / command
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise MCPClientError(f"MCP Python executable is unavailable: {executable}")

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        errlog = open(os.devnull, "w")
        self._stack.callback(errlog.close)
        parameters = StdioServerParameters(
            command=str(executable),
            args=server_config.get("args", []),
            cwd=self.project_root,
        )
        streams = await self._stack.enter_async_context(
            stdio_client(parameters, errlog=errlog)
        )
        self._session = await self._stack.enter_async_context(
            ClientSession(*streams)
        )
        await self._session.initialize()
        self.tool_names = {tool.name for tool in (await self._session.list_tools()).tools}
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._stack is not None:
            await self._stack.__aexit__(exc_type, exc, tb)
        self._stack = None
        self._session = None

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._session is None:
            raise MCPClientError("MCP client is not connected")
        if tool_name not in self.tool_names:
            raise MCPClientError(f"MCP tool is not available: {tool_name}")
        result = await self._session.call_tool(tool_name, arguments=arguments)
        if result.isError:
            raise MCPClientError(f"MCP tool failed: {tool_name}")
        structured = result.structuredContent
        if structured is not None:
            return dict(structured)
        for content in result.content:
            text = getattr(content, "text", None)
            if text:
                return json.loads(text)
        raise MCPClientError(f"MCP tool returned no structured content: {tool_name}")
