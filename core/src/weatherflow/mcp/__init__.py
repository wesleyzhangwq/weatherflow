"""MCP client normalization and WeatherFlow stdio server."""

from weatherflow.mcp.catalog import (
    CuratedMCPCatalog,
    MCPPreset,
    MCPPresetSummary,
    MCPPresetUnavailableError,
    UnknownMCPPresetError,
)
from weatherflow.mcp.client import (
    ConnectedMCP,
    MCPClient,
    MCPExecutor,
    MCPRegistry,
    MCPTransport,
    MCPUnavailableError,
)
from weatherflow.mcp.management import (
    CuratedMCPPresetPackageInstaller,
    InMemoryMCPConnectionRepository,
    MCPConnectionRepository,
    MCPConnectionState,
    MCPInstallationError,
    MCPInstallAuthorization,
    MCPManagedHealth,
    MCPManagementService,
    MCPNotInstalledError,
    MCPPresetPackageInstaller,
    MCPWorkspaceContext,
    NpmMCPPresetPackageInstaller,
    WorkspaceRoutedMCPExecutor,
)
from weatherflow.mcp.repository import SQLiteMCPConnectionRepository
from weatherflow.mcp.server import WeatherFlowMCPServer, serve_stdio
from weatherflow.mcp.transport import StdioMCPTransport

__all__ = [
    "ConnectedMCP",
    "CuratedMCPCatalog",
    "CuratedMCPPresetPackageInstaller",
    "InMemoryMCPConnectionRepository",
    "MCPClient",
    "MCPConnectionRepository",
    "MCPConnectionState",
    "MCPExecutor",
    "MCPInstallAuthorization",
    "MCPInstallationError",
    "MCPManagedHealth",
    "MCPManagementService",
    "MCPNotInstalledError",
    "MCPPreset",
    "MCPPresetPackageInstaller",
    "MCPPresetSummary",
    "MCPPresetUnavailableError",
    "MCPRegistry",
    "MCPTransport",
    "MCPUnavailableError",
    "MCPWorkspaceContext",
    "NpmMCPPresetPackageInstaller",
    "StdioMCPTransport",
    "SQLiteMCPConnectionRepository",
    "UnknownMCPPresetError",
    "WeatherFlowMCPServer",
    "WorkspaceRoutedMCPExecutor",
    "serve_stdio",
]
