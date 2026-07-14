from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class UnknownMCPPresetError(LookupError):
    """Raised when a caller supplies anything outside the curated preset enum."""


class MCPPresetUnavailableError(RuntimeError):
    """Raised when a visible preset is intentionally blocked by policy."""


class MCPPresetSummary(BaseModel):
    """Renderer-safe catalog data; executable and package details stay in Python."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preset_id: str
    title: str
    description: str
    publisher: str
    source_url: str
    version: str
    capabilities: tuple[str, ...]
    risk_note: str
    available: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class MCPPreset:
    preset_id: str
    title: str
    description: str
    publisher: str
    source_url: str
    package_manager: Literal["npm", "python"]
    package_name: str
    package_version: str
    binary_name: str
    capabilities: tuple[str, ...]
    risk_note: str
    requires_action_roots: bool = False
    fixed_arguments: tuple[str, ...] = ()
    available: bool = True
    unavailable_reason: str | None = None

    def to_summary(self) -> MCPPresetSummary:
        return MCPPresetSummary(
            preset_id=self.preset_id,
            title=self.title,
            description=self.description,
            publisher=self.publisher,
            source_url=self.source_url,
            version=self.package_version,
            capabilities=self.capabilities,
            risk_note=self.risk_note,
            available=self.available,
            unavailable_reason=self.unavailable_reason,
        )

    def installation_root(self, internal_root: Path) -> Path:
        root = internal_root.expanduser().resolve()
        return root / "mcp" / "servers" / self.preset_id / self.package_version

    def executable_path(self, internal_root: Path) -> Path:
        target = self.installation_root(internal_root)
        if self.package_manager == "npm":
            return target / "node_modules" / ".bin" / self.binary_name
        return target / "bin" / self.binary_name

    def launch_argv(
        self,
        internal_root: Path,
        *,
        action_roots: tuple[Path, ...],
    ) -> tuple[str, ...]:
        if not self.available:
            raise MCPPresetUnavailableError(self.unavailable_reason or self.preset_id)
        if self.requires_action_roots and not action_roots:
            raise ValueError(f"{self.preset_id} requires at least one Workspace action root")
        root_args = tuple(str(path.expanduser().resolve()) for path in action_roots)
        return (
            str(self.executable_path(internal_root)),
            *self.fixed_arguments,
            *(root_args if self.requires_action_roots else ()),
        )


class CuratedMCPCatalog:
    """A fixed allowlist. No method accepts executable/package metadata from callers."""

    def __init__(self, presets: tuple[MCPPreset, ...]) -> None:
        self._presets = {preset.preset_id: preset for preset in presets}
        if len(self._presets) != len(presets):
            raise ValueError("duplicate MCP preset id")

    @classmethod
    def default(cls) -> CuratedMCPCatalog:
        return cls(
            (
                MCPPreset(
                    preset_id="filesystem",
                    title="本地文件",
                    description="在当前 Workspace 明确授权的目录中读取与编辑文件。",
                    publisher="Model Context Protocol",
                    source_url=(
                        "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem"
                    ),
                    package_manager="npm",
                    package_name="@modelcontextprotocol/server-filesystem",
                    package_version="2026.7.10",
                    binary_name="mcp-server-filesystem",
                    capabilities=("文件读取", "目录检索", "受审批的文件写入"),
                    risk_note="只注入 Workspace action roots；写入工具仍需 Trust 审批。",
                    requires_action_roots=True,
                ),
                MCPPreset(
                    preset_id="playwright",
                    title="浏览器自动化",
                    description="用隔离的无头浏览器进行网页导航、检查与交互。",
                    publisher="Microsoft",
                    source_url="https://github.com/microsoft/playwright-mcp",
                    package_manager="npm",
                    package_name="@playwright/mcp",
                    package_version="0.0.78",
                    binary_name="playwright-mcp",
                    capabilities=("网页导航", "可访问性快照", "受审批的网页交互"),
                    risk_note=(
                        "固定启用 headless、isolated 与浏览器 sandbox；MCP 本身不是安全边界，"
                        "非只读工具仍需 Trust 审批。"
                    ),
                    fixed_arguments=(
                        "--headless",
                        "--isolated",
                        "--sandbox",
                        "--block-service-workers",
                        "--image-responses=omit",
                        "--output-mode=stdout",
                        "--browser=chrome",
                    ),
                ),
                MCPPreset(
                    preset_id="fetch",
                    title="网页抓取",
                    description="把网页正文转换为适合模型阅读的文本。",
                    publisher="Model Context Protocol",
                    source_url="https://github.com/modelcontextprotocol/servers/tree/main/src/fetch",
                    package_manager="python",
                    package_name="mcp-server-fetch",
                    package_version="2026.7.10",
                    binary_name="mcp-server-fetch",
                    capabilities=("网页正文抓取",),
                    risk_note="官方实现可以访问本机与内网地址，当前版本不启用。",
                    available=False,
                    unavailable_reason=(
                        "The official fetch server can access localhost/private networks; "
                        "WeatherFlow has no redirect-safe SSRF boundary for it yet"
                    ),
                ),
            )
        )

    def require(self, preset_id: str) -> MCPPreset:
        try:
            return self._presets[preset_id]
        except KeyError as error:
            raise UnknownMCPPresetError(preset_id) from error

    def summaries(self) -> tuple[MCPPresetSummary, ...]:
        return tuple(
            preset.to_summary()
            for preset in sorted(self._presets.values(), key=lambda item: item.preset_id)
        )
