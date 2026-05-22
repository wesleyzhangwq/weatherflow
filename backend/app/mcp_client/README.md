# MCP Client Infrastructure

This directory contains the MCP (Model Context Protocol) client infrastructure for WeatherFlow's Orchestrator refactor.

## Components

### MCPToolClient (`client.py`)

Low-level wrapper around MCP stdio session. Handles connection setup and tool invocation.

**Usage:**
```python
client = MCPToolClient("uv run python -m mcp_servers.weatherflow_github.server")
async with client.session() as session:
    tools = await client.list_tools(session)
    result = await client.call_tool(session, "github.get_repo_status", {...})
```

### MCPToolRegistry (`tool_registry.py`)

Central catalog of available MCP tools with permission and rate-limit management.

**Permission Model:** Default-deny. Agents must be explicitly granted permission to call tools.

**Key Methods:**
- `register_tool(info)`: Register a tool discovered from an MCP provider
- `grant_permission(agent_id, tool_name, max_calls_per_hour)`: Allow an agent to call a tool
- `can_call_tool(agent_id, tool_name)`: Check if agent can call tool (respects rate limits)
- `get_available_tools(agent_id)`: List tools available to an agent

**Example:**
```python
registry = MCPToolRegistry()

# Register tools from MCP provider
registry.register_tool(ToolInfo("github.get_repo_status", "Get repo status", "github"))

# Grant permissions
registry.grant_permission("dev_review", "github.get_repo_status", max_calls_per_hour=10)

# Check permissions
can_call, reason = registry.can_call_tool("dev_review", "github.get_repo_status")

# List available tools
tools = registry.get_available_tools("dev_review")
```

### AgentToolExecutor (`agent_tool_executor.py`)

Enforces per-agent budgets when calling MCP tools. Tracks call count, token usage, and elapsed time.

**Budgets:**
- `max_calls`: Maximum number of tool calls
- `max_tokens`: Maximum tokens (input + output)
- `max_time_seconds`: Maximum wall-clock time

**Key Methods:**
- `call_tool(session, tool_name, arguments)`: Call tool with budget enforcement
- `get_budget_status()`: Return current budget usage

**Example:**
```python
budget = AgentBudget(max_calls=10, max_tokens=100_000, max_time_seconds=300)
executor = AgentToolExecutor(
    agent_id="dev_review",
    mcp_client=client,
    registry=registry,
    budget=budget,
)

async with client.session() as session:
    result = await executor.call_tool(session, "github.get_repo_status", {})
    status = executor.get_budget_status()
```

## Architecture

### Current State (Tier 0 - Router Prefetch)
- Router calls `provider_registry.get_github_context()` / `get_calendar_context()`
- Prefetches all provider data upfront into `ProviderContext`
- Passes contexts to agent for synthesis

### Target State (Tier 1 - Agent Tool Use)
- Agent holds `MCPToolClient` and `AgentToolExecutor`
- Agent calls tools in a tool_use loop
- Registry enforces permissions and rate limits
- Executor enforces per-agent budgets

## Migration Plan

**Phase 1 (Complete):** Infrastructure
- MCPToolRegistry: Tool catalog with permissions and rate limiting
- AgentToolExecutor: Budget enforcement for agent tool calls
- 20 new tests, all passing

**Phase 2:** FlexibleAgent + DevReviewAgent Migration
- FlexibleAgent: Base class for tool_use loop agents
- Migrate DevReviewAgent to use tools directly
- Update dev_review router to use Tier 1

**Phase 3:** Optimization
- Tool caching
- Parallel tool execution
- Cost estimation

**Phase 4:** Cleanup
- Remove direct mode (keep MCP + dual)
- Remove Tier 0 prefetch pattern
- Consolidate router

## Testing

Run tests:
```bash
uv run python -m pytest backend/tests/test_tool_registry.py backend/tests/test_agent_tool_executor.py -v
```

All tests pass: 20/20
