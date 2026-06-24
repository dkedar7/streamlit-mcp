"""streamlit-mcp — serve a Streamlit app as an MCP server, no browser.

The app is driven headlessly through Streamlit's AppTest runtime (behind a Runtime
interface); widgets auto-map to MCP tools, and a human-first CLI exercises the same
engine an agent uses (parity).
"""

__version__ = "0.1.2"

# Public API
from .decorator import mcp_tool  # noqa: E402
from .engine import Engine, PermissionDenied  # noqa: E402
from .guardrails import Guardrails  # noqa: E402
from .runtime import AppTestRuntime, Runtime, RuntimeError_, WidgetNotFound  # noqa: E402
from .server import build_server, serve  # noqa: E402

__all__ = [
    "__version__",
    "mcp_tool",
    "Engine",
    "PermissionDenied",
    "Guardrails",
    "AppTestRuntime",
    "Runtime",
    "RuntimeError_",
    "WidgetNotFound",
    "build_server",
    "serve",
]
