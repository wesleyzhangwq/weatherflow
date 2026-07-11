# WeatherFlow v3 MCP

WeatherFlow is both an MCP client and a stdio MCP server. Both directions are
adapters around the same Run, ToolSpec, Workspace, and Trust Plane contracts.

## Client

`MCPRegistry` initializes a typed transport, discovers `tools/list`, and
normalizes each remote tool to a canonical ID:

```text
mcp.<server>.<remote-tool>
```

`readOnlyHint` maps to `network_read`, unannotated writes map conservatively to
`external_write`, and `destructiveHint` maps to `destructive`. Every tool also
requires the explicit `mcp:<server>:use` Workspace scope; annotations never
grant that scope. Write, destructive, install, and sensitive calls reject
direct executor use without an approved Action context.

Connected tools enter the global catalog, but a Workspace must install a
verified Capability Pack that names the exact MCP tool IDs. Only that smallest
set is frozen into a new Run. Existing Runs retain their original schemas.
Disconnects hide cached tools as unavailable; a failed read becomes a bounded
observation, while an uncertain approved external call follows normal
`NEEDS_REVIEW` semantics.

`StdioMCPTransport` uses argv-only subprocess execution, a reduced environment,
serialized request IDs, bounded response wait, and a redacted representation.

## Server

Run the local server with:

```bash
weatherflow --data-dir ~/.local/share/weatherflow mcp-server
```

It exposes:

- `weatherflow.submit_run`
- `weatherflow.get_run`
- `weatherflow.timeline`
- `weatherflow.list_approvals`
- `weatherflow.decide_approval`

Submission calls `RuntimeContainer.submit_run`, so MCP retries use the same
`client_request_id` idempotency and cannot create an alternate execution path.
Approval decisions call `ApprovalCoordinator` and resume the same durable
checkpoint. JSON-RPC errors are bounded and do not include stack traces or
credentials.
