# WeatherFlow v3 生产化指标报告

- Benchmark: `weatherflow-v3-production-metrics-v2`
- Generated: `2026-07-21T09:27:16.341731+00:00`
- Git commit: `cfa42fdf0025c11809387b9dc548a40524960532`; dirty: `false`
- Dataset hash: `1afd4dbd8865c45575920035d2ff5076c7d579d51cd026cf69d9b29a62e9d7f7`
- Command: `uv run --package weatherflow-core --extra dev python tools/weatherflow_metrics.py --repetitions 3 --output-root /Users/wesz_station/Projects/WeatherFlow/eval/results/weatherflow-v3-production-metrics-v2`
- External API calls: `0`（模型与故障均为确定性 fixture；不把 fixture 冒充线上流量）

## 结论

- Overall: `PASS`
- Recovery success: `100.00%` (27/27)
- Resume latency: P50 `38.869` ms, P95 `51.425` ms, n=`27`
- Rebuild + resume latency: P50 `168.107` ms, P95 `235.427` ms, n=`27`
- Duplicate model calls: `0`; duplicate tool calls: `3`; duplicate external side effects: `0`
- Isolation pass: `100.00%` (12/12); skipped: `0`
- Production-security complete: `true` (requires skipped=`0`)
- Escape / unauthorized execution / approval bypass: `0` / `0` / `0`

`resume_latency_ms` 只测 `resume_run`；`rebuild_plus_resume_latency_ms` 同时包含 `RuntimeContainer.create`。P95 使用 nearest-rank，样本量 n 明示；小样本不表述为稳定生产 SLO。

## 恢复矩阵

| Case | 持久化边界与核心断言 | n | Pass | Resume P50/P95 ms | Dup model/tool/external |
|---|---|---:|---:|---:|---:|
| `run_created_not_started` | Run, frozen capability snapshot, model route, and connector route exist; execution has not started; rebuilt RuntimeContainer completes the same Run with all frozen identities unchanged | 3 | 3 | 47.161/49.785 | 0/0/0 |
| `model_turn_checkpointed` | final model turn is the durable pending_turn; terminal Run commit is faulted; rebuild commits the pending final without another model call | 3 | 3 | 25.412/25.482 | 0/0/0 |
| `tool_call_persisted_before_observation` | tool call is pending in RunCheckpoint; dispatcher is faulted before execution; rebuild executes the frozen read tool once, records observation, and completes | 3 | 3 | 43.324/43.55 | 0/0/0 |
| `waiting_approval` | Run is WAITING_APPROVAL with durable Action and Approval identities; rebuild returns the same identities, performs no write before decision, then executes once after approval | 3 | 3 | 11.092/11.548 | 0/0/0 |
| `encrypted_provider_continuation` | encrypted provider continuation and tool observation are durable before the next model request; private payload is absent from ordinary checkpoint/tables, restored after rebuild, and deleted at terminal | 3 | 3 | 35.98/47.76 | 0/0/0 |
| `read_tool_succeeded_before_observation` | read-only executor returned successfully; observation commit is faulted; rebuild safely replays the read and completes; one duplicate read call is reported | 3 | 3 | 43.846/49.76 | 0/3/0 |
| `external_action_succeeded_before_observation` | external Action is SUCCEEDED with durable result; observation commit is faulted; rebuild recovers the receipt and never repeats the external side effect | 3 | 3 | 51.14/51.425 | 0/0/0 |
| `external_action_executing_unknown` | approved external Action is EXECUTING with unknown result semantics; rebuild calls no executor and moves both Action and Run to NEEDS_REVIEW | 3 | 3 | 34.337/53.168 | 0/0/0 |
| `corrupt_checkpoint` | RunCheckpoint state contains malformed persisted JSON; rebuild removes the active row, stores hash/reason in quarantine, emits event, and requires review | 3 | 3 | 21.61/21.765 | 0/0/0 |

只读工具在“执行成功但 observation 未提交”的边界会安全重放，因此该场景明确报告 1 次 duplicate tool call/样本；这不是外部副作用重复。已成功外部 Action 使用持久化 receipt 恢复，外部副作用重复数目标与结果均为 0。EXECUTING 且结果未知的 Action 必须进入 NEEDS_REVIEW。

## 权限隔离矩阵

| Case | Result | Evidence |
|---|---|---|
| `missing_required_scope` | `passed` | SupervisedPolicy denied a tool whose required scope was absent |
| `tool_outside_frozen_snapshot` | `passed` | SharedTurnLoop converted an out-of-snapshot call into an observation |
| `workspace_outside_read` | `passed` | DeveloperExecutor rejected an absolute path outside action roots |
| `workspace_outside_write` | `passed` | DeveloperExecutor rejected an outside write and created no file |
| `offline_network` | `passed` | host reached a selected public TCP endpoint; Seatbelt denied both loopback and that exact numeric target |
| `loopback_only_network` | `passed` | host reached a selected public TCP endpoint; Seatbelt allowed loopback while denying that exact numeric target |
| `keychain_access` | `passed` | Seatbelt denied Keychain enumeration and returned no stdout |
| `unapproved_external_write` | `passed` | external write parked durably before executor invocation |
| `install_requires_approval` | `passed` | install policy required approval and MCP installer was not invoked |
| `destructive_requires_approval` | `passed` | destructive operation parked for approval before executor invocation |
| `mcp_allowlist_bypass` | `passed` | unexpected MCP discovery failed closed and exposed no active tools |
| `sandbox_unavailable_fail_closed` | `passed` | missing Seatbelt backend raised before spawning a child process |

生产安全结论要求真实 Seatbelt 用例全部执行且 skipped=0；任何 skipped 都会令 Overall=FAIL。portable CI 可验证其余合同，但不能产出 production-security PASS。网络负例先让宿主连通选定公网服务的精确 IPv4/端口，再让 Seatbelt 验证同一数值目标；目标不可达时不会把网络故障误报成沙箱拦截。该正控只建立 TCP 连接，不发送 TLS 或应用层请求。

## 按 Run 成本可观测样本

| Case | Provider/model | Billing origin | Tokens in/cache-read/out/total | Amount/currency | Cost USD | Status/catalog | Budget result |
|---|---|---|---:|---:|---:|---|---|
| `minimax_global_paygo_usd_known` | `minimax/MiniMax-M2.7` | `minimax_global_paygo` | 1200/0/300/1500 | 0.00072 / `USD` | 0.00072 | `known` / `minimax-global-paygo-usd-2026-07-21` | `within_budget` / `none` |
| `minimax_cn_paygo_cny_known_usd_budget_unknown` | `minimax/MiniMax-M2.7` | `minimax_cn_paygo` | 1200/0/300/1500 | 0.00504 / `CNY` | unknown | `known` / `minimax-cn-paygo-cny-2026-07-21` | `unknown_cost` / `cost_unknown` |
| `minimax_token_plan_cost_unknown` | `minimax/MiniMax-M2.7` | `minimax_cn_token_plan` | 800/0/100/900 | unknown / `none` | unknown | `unknown` / `none` | `unknown_cost` / `cost_unknown` |
| `unpriced_openai_cost_unknown` | `openai/gpt-unpriced-compatible` | `unconfirmed` | 800/unknown/100/900 | unknown / `none` | unknown | `unknown` / `none` | `unknown_cost` / `cost_unknown` |

MiniMax pricing catalogs are independent by billing origin and currency: `minimax_global_paygo` / `USD` / `minimax-global-paygo-usd-2026-07-21` ([https://platform.minimax.io/docs/guides/pricing-paygo](https://platform.minimax.io/docs/guides/pricing-paygo), [https://platform.minimax.io/docs/api-reference/text-prompt-caching](https://platform.minimax.io/docs/api-reference/text-prompt-caching)); `minimax_cn_paygo` / `CNY` / `minimax-cn-paygo-cny-2026-07-21` ([https://platform.minimaxi.com/docs/guides/pricing-paygo](https://platform.minimaxi.com/docs/guides/pricing-paygo))

所有样本的 `cost_scope=model_usage_only`，只覆盖模型 token 用量，不代表税费、订阅费、Credits 或最终账单。MiniMax 样本使用明确 `cached_tokens=0` 的 deterministic provider-shaped fixture；它不是实付或线上观测成本。计费类型由冻结的 `billing_origin` 明示，绝不从 hostname 推断：全球 PayGo 保留 USD，中国 PayGo 保留 CNY 且不做 FX；Token Plan 或未确认类型保持 unknown。缺少缓存明细、目录或明确计费来源时也保持 unknown，有限 USD 预算继续 fail-closed；unknown 从未当作 0。样本均不调用外部 API。

## 可复现性与边界

- Recovery repetitions: `3`; concurrency: `1`; warmup: `0`.
- Raw evidence is one JSON object per case/sample in `raw_results.jsonl`; aggregate values are in `summary.json`.
- Model, connector, and capability identities are compared before/after every RuntimeContainer rebuild using stable hashes or IDs.
- The continuation case checks ordinary checkpoint and every non-continuation SQLite table for the private fixture marker, then verifies encrypted-row deletion at terminal.
- This is a deterministic recovery/security benchmark, not a live-provider availability or paid-traffic benchmark.
