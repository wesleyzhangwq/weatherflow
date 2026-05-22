# Orchestrator Refactor - Phase 1 Completion

**Completed:** 2026-05-22  
**Status:** ✅ All 20 new tests pass, full suite 114/114 pass

## What Was Implemented

### 1. MCPToolRegistry (`backend/app/mcp_client/tool_registry.py`)

Central catalog of available MCP tools with permission and rate-limit management.

**Key features:**
- Tool registration and discovery
- Permission model: default-deny (agents must be explicitly granted access)
- Rate limiting: per-tool limits (max_calls_per_hour)
- Methods:
  - `register_tool(info)`: Register a tool from MCP provider
  - `grant_permission(agent_id, tool_name, max_calls_per_hour)`: Authorize agent access
  - `can_call_tool(agent_id, tool_name)`: Permission + rate limit check
  - `get_available_tools(agent_id)`: List authorized tools
  - `record_tool_call(tool_name)`: Track call history

**Tests:** 12 tests covering registration, permissions, rate limiting, and edge cases

### 2. AgentToolExecutor (`backend/app/mcp_client/agent_tool_executor.py`)

Enforces per-agent budgets when calling MCP tools via MCPToolClient.

**Key features:**
- Per-agent budgets:
  - `max_calls`: Total tool invocations allowed
  - `max_tokens`: Total tokens (estimated input+output)
  - `max_time_seconds`: Wall-clock time limit
- Call method: `call_tool(session, tool_name, arguments)`
- Budget monitoring: `get_budget_status()` returns usage
- Exceptions:
  - `PermissionDenied`: Agent lacks tool permission
  - `BudgetExceeded`: Any budget limit reached

**Tests:** 8 tests covering permission checks, budget enforcement, and tracking

### 3. Test Coverage

Created 2 new test files with 20 comprehensive tests:
- `test_tool_registry.py`: 112 lines, 12 tests
- `test_agent_tool_executor.py`: 145 lines, 8 tests

All tests passing. No regression in existing 94 tests.

### 4. Documentation

- `README.md`: Architecture overview, components, usage examples
- `INTEGRATION_EXAMPLE.md`: Step-by-step integration guide for agents
- Updated `__init__.py` with clean exports

## Architecture

### Current (Tier 0 - Router Prefetch)
```
Router:
  1. Call provider_registry.get_github_context()
  2. Call provider_registry.get_calendar_context()
  3. Pass [ProviderContext] to Agent
  
Agent:
  4. Synthesize review from pre-fetched contexts
```

### Phase 1 Infrastructure (New)
```
MCPToolRegistry: Tool catalog + permissions + rate limits
  ├── register_tool(info)
  ├── grant_permission(agent_id, tool_name)
  └── can_call_tool(agent_id, tool_name)

AgentToolExecutor: Budget enforcement + MCP client wrapper
  ├── call_tool(session, tool_name, args)  [enforces budget + permission]
  └── get_budget_status()
```

### Phase 2 Target (Tier 1 - Agent Tool Use)
```
Agent:
  1. Hold MCPToolClient + AgentToolExecutor
  2. Loop: call executor.call_tool() for needed data
  3. Respond to budget/permission errors
  
Router:
  4. Just create registry, executor, pass to agent
  5. Agent owns tool calling
```

## Migration Path

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Registry + Executor infrastructure | ✅ Complete |
| 2 | FlexibleAgent base class + DevReviewAgent migration | To start |
| 3 | Tool caching, parallel execution, cost estimation | To plan |
| 4 | Cleanup: remove direct/dual modes, Tier 0 prefetch | To schedule |

## Key Design Decisions

1. **Permission Model:** Default-deny (more secure than default-allow)
   - Agents must be explicitly granted per-tool access
   - Enforced in both permission check and availability listing

2. **Budget Types:** Three independent budgets
   - Call count: Prevents excessive tool invocations
   - Token count: Controls LLM context size
   - Time: Prevents runaway execution

3. **Registry as Singleton:** Shared across all agents
   - One source of truth for tool availability
   - Centralized rate limit tracking
   - Each agent gets its own executor instance

4. **Executor Lifecycle:** One executor per agent run
   - Fresh budget for each execution
   - Easier to debug and monitor
   - Clean separation from agent state

## Next Steps (Phase 2)

1. **Create FlexibleAgent base class**
   - Holds MCPToolClient and AgentToolExecutor
   - Implements tool-use loop pattern
   - Provides error handling for budget/permission errors

2. **Migrate DevReviewAgent**
   - Instead of receiving ProviderContext list, receive executor
   - Call `executor.call_tool()` to fetch GitHub/Calendar data
   - Implement tool-use loop in `synthesize_with_tools()`

3. **Update dev_review router**
   - Create registry and executor (move from Tier 0 to Tier 1)
   - Pass executor to agent
   - Agent is responsible for fetching data

4. **Run migration tests**
   - Ensure DevReviewAgent produces same outputs
   - Verify budget/permission enforcement works
   - Parallel run (Tier 0 + Tier 1) for validation

## Files Changed

**New files:**
- `backend/app/mcp_client/tool_registry.py` (200 lines)
- `backend/app/mcp_client/agent_tool_executor.py` (140 lines)
- `backend/app/mcp_client/README.md` (documentation)
- `backend/app/mcp_client/INTEGRATION_EXAMPLE.md` (integration guide)
- `backend/tests/test_tool_registry.py` (112 lines, 12 tests)
- `backend/tests/test_agent_tool_executor.py` (145 lines, 8 tests)

**Modified files:**
- `backend/app/mcp_client/__init__.py` (added exports)
- Memory: `project_mcp_migration.md` (updated with Phase 1 status)

## Testing Commands

```bash
# Run Phase 1 tests
uv run python -m pytest backend/tests/test_tool_registry.py backend/tests/test_agent_tool_executor.py -v

# Run full suite
uv run python -m pytest backend/tests -q
```

Result: ✅ 20/20 Phase 1 tests, 114/114 total tests
