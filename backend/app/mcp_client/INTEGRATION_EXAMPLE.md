# AgentToolExecutor Integration Example

This document shows how to integrate `MCPToolRegistry` and `AgentToolExecutor` into an agent.

## Step 1: Initialize Registry and Grant Permissions

```python
from app.mcp_client.tool_registry import MCPToolRegistry, ToolInfo
from app.mcp_client.client import MCPToolClient

# Create registry
registry = MCPToolRegistry()

# Register tools from MCP providers
github_tools = [
    ToolInfo("github.get_repo_status", "Get repository status", "github"),
    ToolInfo("github.list_issues", "List open issues", "github"),
    ToolInfo("github.get_user_events", "Get recent user events", "github"),
]

for tool in github_tools:
    registry.register_tool(tool)

# Grant permissions for dev_review agent
for tool in github_tools:
    registry.grant_permission(
        "dev_review",
        tool.name,
        max_calls_per_hour=10,
    )

# Verify what's available
available = registry.get_available_tools("dev_review")
print(f"Available tools: {[t.name for t in available]}")
```

## Step 2: Create MCP Client and Executor

```python
from app.mcp_client.agent_tool_executor import AgentToolExecutor, AgentBudget
from app.config import get_settings

settings = get_settings()

# Create MCP client
mcp_client = MCPToolClient(settings.wf_github_mcp_command)

# Create budget for this agent run
budget = AgentBudget(
    max_calls=5,           # Max 5 tool calls
    max_tokens=50_000,     # Max 50k tokens
    max_time_seconds=60.0, # Max 1 minute
)

# Create executor
executor = AgentToolExecutor(
    agent_id="dev_review",
    mcp_client=mcp_client,
    registry=registry,
    budget=budget,
)
```

## Step 3: Use Executor in Agent Loop

```python
from app.mcp_client.agent_tool_executor import BudgetExceeded, PermissionDenied

async def dev_review_with_tools():
    async with mcp_client.session() as session:
        # Step 1: Get initial context
        try:
            events = await executor.call_tool(
                session,
                "github.get_user_events",
                {"days": 7},
            )
            print(f"Recent events: {len(events)}")
        except PermissionDenied as e:
            print(f"Permission denied: {e}")
            return
        except BudgetExceeded as e:
            print(f"Budget exceeded: {e}")
            return

        # Step 2: Get specific issues if needed
        if events and events.get("has_open_issues"):
            try:
                issues = await executor.call_tool(
                    session,
                    "github.list_issues",
                    {"limit": 5},
                )
                print(f"Found {len(issues)} issues")
            except BudgetExceeded:
                print("Running out of budget, stopping here")
                return

        # Step 3: Check budget status
        status = executor.get_budget_status()
        print(f"Budget status: {status}")
        # Output:
        # {
        #   "calls": {"used": 2, "limit": 5},
        #   "tokens": {"used": 1500, "limit": 50000},
        #   "time_seconds": {"used": 0.5, "limit": 60.0}
        # }
```

## Step 4: Update Router (Future: Phase 2)

Currently, the router prefetches contexts. After Phase 2, it will be:

```python
@router.post("/api/dev-review/runs", response_model=DevReviewRecord)
async def create_dev_review_run(
    payload: DevReviewRunRequest,
    request: Request,
) -> DevReviewRecord:
    settings = get_settings()
    
    # Create registry and executor (moved from router to agent)
    registry = MCPToolRegistry()
    for tool in discover_tools_from_providers(settings):
        registry.register_tool(tool)
        registry.grant_permission("dev_review", tool.name)
    
    mcp_client = MCPToolClient(settings.wf_github_mcp_command)
    executor = AgentToolExecutor(
        agent_id="dev_review",
        mcp_client=mcp_client,
        registry=registry,
        budget=AgentBudget(max_calls=10),
    )
    
    # Agent now holds executor and calls tools directly
    review = await DevReviewAgent(get_llm(request)).synthesize_with_tools(
        window_days=payload.window_days,
        executor=executor,  # Pass executor to agent
    )
    
    return dev_review_repo.create_review(review)
```

## Key Points

1. **Permission Model:** Must explicitly grant permissions via `grant_permission()`
2. **Rate Limiting:** Per-agent rate limits configured when granting permission
3. **Budgets:** Separate budget for each agent run (call count, tokens, time)
4. **Error Handling:** Catch `PermissionDenied` and `BudgetExceeded` exceptions
5. **Monitoring:** Use `get_budget_status()` to track usage

## Testing

Integration tests verify:
- Permissions are enforced
- Budgets prevent excessive calls
- Rate limits are respected
- Tool calls are recorded in registry

```bash
uv run python -m pytest backend/tests/test_agent_tool_executor.py::test_call_tool_raises_when_call_budget_exceeded -v
```
