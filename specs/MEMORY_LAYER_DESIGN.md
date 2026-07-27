# Memory Layer — Phase 5 of the Educational Agent OS

> Implemented in `backend/app/ai/memory/`. Companion to the Context Engine
> (Phase 4) and the registries (Phases 2–3). **Provider-independent by
> construction**: the interfaces know nothing of SQLAlchemy, the SDK, or any
> backend — stores are injected, and swapping one is invisible to callers.

## 1. One abstraction, typed scopes

Everything is a scoped `MemoryRecord` behind one `MemoryStore` contract
(`append` / `recall` / `forget` / `clear_scope`), routed by `MemoryService`:

| Scope | scope_ref | Backing | Use |
|---|---|---|---|
| `WORKFLOW` | workflow_id | durable (ai_memories) | facts about a workflow instance — rejection feedback is captured here automatically |
| `SESSION` | session_id | durable | notes attached to a conversation session |
| `CONVERSATION` | session_id | **adapter over ai_messages** | the transcript — one canonical storage, never double-stored; the SDK session (runtime/sessions.py) now reads/writes through this adapter |
| `ARTIFACT` | `"workflow_id:stage_key"` | durable | annotations about a produced artifact |
| `AGENT` | agent_key (per user) | durable | per-user, per-agent persistent facts — what the memory tools use |
| `SHORT_TERM` | free ref (e.g. run id) | **in-process store**, TTL | ephemeral scratch; expired records filtered on read and lazily purged |
| `LONG_TERM` | — | **reserved** | the `SemanticMemoryStore` protocol (index/similar) is defined and deliberately unimplemented — an embedding/vector backend plugs in behind it later |

Records are immutable (frozen dataclass, read-only content mapping); writes
with the same `key` upsert; `recall` supports key-exact and substring-query
retrieval (semantic similarity later = a different store, same signature).

## 2. Module map

| File | Responsibility |
|---|---|
| `memory/interfaces.py` | `MemoryScope`, `MemoryRecord`, `MemoryQuery`, `MemoryStore`, `SemanticMemoryStore` (future seam) — zero backend imports |
| `memory/stores.py` | `DatabaseMemoryStore` (ai_memories, migration `11`/Alembic `0005`) and `InProcessMemoryStore` (short-term default + test double) |
| `memory/service.py` | `MemoryService`: scope routing (SHORT_TERM → in-process, rest → durable), typed helpers (`remember_workflow/agent/session/artifact/short_term`), the conversation adapter, and `set_stores()` DI |

## 3. Integrations (memory is used, not shelved)

- **Agent memory tools** (`memory.remember` / `memory.recall`, permission
  `memory.self` for all roles): teacher_assistant and student_assistant can
  persist and retrieve user facts across conversations. Strictly
  self-scoped — records key on (user, executing agent); tests verify a
  different agent key sees nothing.
- **Context Engine facet**: `AgentMemoryProvider` surfaces the caller's
  agent-scope memories into `AgentExecutionContext.memories` before every
  run — agents start context-aware of what they previously learned.
- **Workflow memory**: rejecting an assessment checkpoint records the
  reviewer's notes as workflow memory (`rejection:<stage>:rev<N>`), so
  future agent-backed stage runs can recall why revisions happened
  (failure-guarded — memory can never break a decision).
- **SDK sessions**: `runtime/sessions.py` now goes through the conversation
  adapter — the Memory Layer is the single doorway to the transcript.

## 4. Provider independence, concretely

`MemoryService(durable=..., short_term=...)` takes any `MemoryStore`;
`memory_service.set_stores()` swaps backends at runtime (how every test runs
DB-free). Adding Redis, a vector DB, or a remote memory service means
implementing one protocol — no caller, tool, provider, or workflow changes.
