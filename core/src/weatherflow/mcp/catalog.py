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
    package_manager: Literal["npm", "python", "builtin"]
    package_name: str
    package_version: str
    binary_name: str
    capabilities: tuple[str, ...]
    risk_note: str
    allowed_tool_names: tuple[str, ...] = ()
    requires_action_roots: bool = False
    fixed_arguments: tuple[str, ...] = ()
    state_filename: str | None = None
    state_environment_key: Literal["MEMORY_FILE_PATH"] | None = None
    available: bool = True
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if len(set(self.allowed_tool_names)) != len(self.allowed_tool_names):
            raise ValueError(f"duplicate MCP tool name for preset {self.preset_id}")
        if self.available and not self.allowed_tool_names:
            raise ValueError(f"available MCP preset {self.preset_id} requires a tool allowlist")
        if (self.state_filename is None) != (self.state_environment_key is None):
            raise ValueError("MCP state filename and environment key must be configured together")
        if self.state_filename is not None and (
            Path(self.state_filename).name != self.state_filename
            or self.state_filename in {"", ".", ".."}
        ):
            raise ValueError("MCP state filename must be one plain filename")

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
        if self.package_manager == "builtin":
            return target / ".weatherflow-builtin-mcp"
        if self.package_manager == "npm":
            return target / "node_modules" / ".bin" / self.binary_name
        return target / "bin" / self.binary_name

    def state_root(self, internal_root: Path) -> Path:
        root = internal_root.expanduser().resolve()
        return root / "mcp" / "state" / self.preset_id

    def state_file(self, internal_root: Path) -> Path | None:
        if self.state_filename is None:
            return None
        return self.state_root(internal_root) / self.state_filename

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
                    allowed_tool_names=(
                        "read_file",
                        "read_text_file",
                        "read_media_file",
                        "read_multiple_files",
                        "write_file",
                        "edit_file",
                        "create_directory",
                        "list_directory",
                        "list_directory_with_sizes",
                        "move_file",
                        "search_files",
                        "directory_tree",
                        "get_file_info",
                        "list_allowed_directories",
                    ),
                    requires_action_roots=True,
                ),
                MCPPreset(
                    preset_id="memory",
                    title="知识图谱记忆",
                    description="用本地知识图谱保存实体、关系与可检索观察。",
                    publisher="Model Context Protocol",
                    source_url=(
                        "https://github.com/modelcontextprotocol/servers/tree/main/src/memory"
                    ),
                    package_manager="npm",
                    package_name="@modelcontextprotocol/server-memory",
                    package_version="2026.7.4",
                    binary_name="mcp-server-memory",
                    capabilities=("实体关系记忆", "本地检索", "受审批的记忆增删"),
                    risk_note=(
                        "只可写入当前 Workspace 的私有 MCP 状态目录；增删仍需 Trust 审批，"
                        "并随“清除记忆”一起删除。"
                    ),
                    allowed_tool_names=(
                        "create_entities",
                        "create_relations",
                        "add_observations",
                        "delete_entities",
                        "delete_observations",
                        "delete_relations",
                        "read_graph",
                        "search_nodes",
                        "open_nodes",
                    ),
                    state_filename="memory.jsonl",
                    state_environment_key="MEMORY_FILE_PATH",
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
                    available=False,
                    unavailable_reason=(
                        "WeatherFlow has no redirect-safe public-network broker for a "
                        "sandboxed browser server yet"
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
                MCPPreset(
                    preset_id="time",
                    title="时间与时区",
                    description="查询 IANA 时区当前时间并进行时区转换。",
                    publisher="Model Context Protocol",
                    source_url=(
                        "https://github.com/modelcontextprotocol/servers/tree/main/src/time"
                    ),
                    package_manager="builtin",
                    package_name="weatherflow-builtin-time",
                    package_version="3.0.0",
                    binary_name="time",
                    capabilities=("当前时间", "时区转换"),
                    risk_note=("WeatherFlow 内置只读实现；通过离线 Seatbelt 沙箱运行。"),
                    allowed_tool_names=("get_current_time", "convert_time"),
                ),
                MCPPreset(
                    preset_id="git-readonly",
                    title="Git 只读检查",
                    description="查看当前 Workspace 仓库状态、差异、历史、分支与提交内容。",
                    publisher="Model Context Protocol",
                    source_url=(
                        "https://github.com/modelcontextprotocol/servers/tree/main/src/git"
                    ),
                    package_manager="builtin",
                    package_name="weatherflow-builtin-git-readonly",
                    package_version="3.0.0",
                    binary_name="git-readonly",
                    capabilities=("仓库状态", "差异与历史", "分支只读检查"),
                    risk_note=(
                        "只计划暴露官方只读工具并以只读 Workspace 根运行；"
                        "写入类 Git 工具不进入白名单。"
                    ),
                    allowed_tool_names=(
                        "git_status",
                        "git_diff_unstaged",
                        "git_diff_staged",
                        "git_diff",
                        "git_log",
                        "git_show",
                        "git_branch",
                    ),
                    requires_action_roots=True,
                ),
                MCPPreset(
                    preset_id="context7",
                    title="Context7 文档",
                    description="按库与版本检索最新技术文档和代码示例。",
                    publisher="Upstash",
                    source_url="https://github.com/upstash/context7",
                    package_manager="npm",
                    package_name="@upstash/context7-mcp",
                    package_version="3.2.3",
                    binary_name="context7-mcp",
                    capabilities=("库识别", "版本化文档检索"),
                    risk_note="需要公共网络访问；当前通用 HTTPS 沙箱不能约束重定向后的目标地址。",
                    available=False,
                    unavailable_reason=(
                        "WeatherFlow has no redirect-safe host-bound egress broker for remote MCP "
                        "documentation requests yet"
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
            if preset.available
        )
