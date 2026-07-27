"""Unit tests for the Memory Layer (Phase 5): interfaces, the in-process
store (TTL, upsert, search), MemoryService scope routing and typed helpers,
provider independence (store swapping), the conversation adapter, the agent
memory tools, and the Context Engine memories facet. No DB required."""
import dataclasses
import uuid
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.ai.context import AIRunContext
from app.ai.context_engine.models import AgentExecutionContext
from app.ai.context_engine.providers import AgentMemoryProvider
from app.ai.memory.interfaces import MemoryQuery, MemoryRecord, MemoryScope, freeze_content
from app.ai.memory.service import MemoryService, memory_service
from app.ai.memory.stores import InProcessMemoryStore
from app.ai.tools import registry as tools


@pytest.fixture
def service() -> MemoryService:
    """A MemoryService fully on in-process stores (no DB)."""
    return MemoryService(durable=InProcessMemoryStore(), short_term=InProcessMemoryStore())


@pytest.fixture
def swapped_singleton():
    """Swap the module singleton onto in-process stores; restore after."""
    previous = memory_service.set_stores(
        durable=InProcessMemoryStore(), short_term=InProcessMemoryStore()
    )
    yield memory_service
    memory_service.set_stores(durable=previous[0], short_term=previous[1])


def _record(user_id, scope=MemoryScope.AGENT, scope_ref="grader", **kw) -> MemoryRecord:
    defaults = dict(
        id=uuid.uuid4(),
        scope=scope,
        scope_ref=scope_ref,
        user_id=user_id,
        content=freeze_content({"text": "fact"}),
    )
    defaults.update(kw)
    return MemoryRecord(**defaults)


class TestInterfaces:
    def test_record_is_frozen_and_content_read_only(self):
        record = _record(uuid4())
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.key = "x"
        with pytest.raises(TypeError):
            record.content["text"] = "mutated"  # type: ignore[index]


class TestInProcessStore:
    def test_append_recall_roundtrip_newest_first(self):
        store, user = InProcessMemoryStore(), uuid4()
        store.append(_record(user, content=freeze_content({"text": "first"}),
                             created_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        store.append(_record(user, content=freeze_content({"text": "second"})))
        got = store.recall(MemoryQuery(scope=MemoryScope.AGENT, scope_ref="grader", user_id=user))
        assert [r.content["text"] for r in got] == ["second", "first"]

    def test_same_key_upserts(self):
        store, user = InProcessMemoryStore(), uuid4()
        store.append(_record(user, key="pref", content=freeze_content({"text": "old"})))
        store.append(_record(user, key="pref", content=freeze_content({"text": "new"})))
        got = store.recall(
            MemoryQuery(scope=MemoryScope.AGENT, scope_ref="grader", user_id=user, key="pref")
        )
        assert len(got) == 1 and got[0].content["text"] == "new"

    def test_query_substring_search(self):
        store, user = InProcessMemoryStore(), uuid4()
        store.append(_record(user, content=freeze_content({"text": "prefers MCQ exams"})))
        store.append(_record(user, content=freeze_content({"text": "teaches physics"})))
        got = store.recall(
            MemoryQuery(scope=MemoryScope.AGENT, scope_ref="grader", user_id=user, query="mcq")
        )
        assert len(got) == 1 and "MCQ" in got[0].content["text"]

    def test_ttl_expiry_filtered_on_read(self):
        store, user = InProcessMemoryStore(), uuid4()
        store.append(_record(user, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        store.append(_record(user, content=freeze_content({"text": "live"})))
        got = store.recall(MemoryQuery(scope=MemoryScope.AGENT, scope_ref="grader", user_id=user))
        assert len(got) == 1 and got[0].content["text"] == "live"

    def test_forget_and_clear_scope(self):
        store, user = InProcessMemoryStore(), uuid4()
        store.append(_record(user, key="a"))
        store.append(_record(user, key="b"))
        assert store.forget(MemoryScope.AGENT, "grader", user, key="a") == 1
        assert store.forget(MemoryScope.AGENT, "grader", user) == 1
        store.append(_record(user))
        assert store.clear_scope(MemoryScope.AGENT, "grader") == 1

    def test_user_isolation(self):
        store, user_a, user_b = InProcessMemoryStore(), uuid4(), uuid4()
        store.append(_record(user_a))
        got = store.recall(MemoryQuery(scope=MemoryScope.AGENT, scope_ref="grader", user_id=user_b))
        assert got == ()


class TestMemoryService:
    def test_short_term_routed_to_short_term_store(self, service):
        user = uuid4()
        service.remember_short_term("run:1", user, {"scratch": 1})
        service.remember_agent(user, "grader", {"text": "durable"})
        assert len(service.recall_short_term("run:1", user)) == 1
        # the short-term record is not in the durable store's scope
        assert service.recall(MemoryScope.SHORT_TERM, "run:1", user)  # routed consistently
        assert len(service.recall_agent(user, "grader")) == 1

    def test_typed_scope_refs(self, service):
        user, wf = uuid4(), uuid4()
        service.remember_workflow(wf, user, {"notes": "revise"}, key="rejection:design:rev1")
        service.remember_artifact(wf, "quality_review", user, {"note": "weak coverage"})
        assert service.recall_workflow(wf, user)[0].key == "rejection:design:rev1"
        artifact = service.recall_artifact(wf, "quality_review", user)
        assert artifact[0].scope_ref == f"{wf}:quality_review"

    def test_provider_independence_store_swap(self, service):
        class RecordingStore(InProcessMemoryStore):
            def __init__(self):
                super().__init__()
                self.appended = 0

            def append(self, record):
                self.appended += 1
                return super().append(record)

        recording = RecordingStore()
        service.set_stores(durable=recording)
        service.remember_agent(uuid4(), "grader", {"text": "x"})
        assert recording.appended == 1

    def test_conversation_adapter_delegates_to_transcript_store(self, service, monkeypatch):
        calls = {}
        import app.ai.persistence.store as pstore

        monkeypatch.setattr(pstore, "get_session_items", lambda sid, limit=None: [{"role": "user"}])
        monkeypatch.setattr(
            pstore, "add_session_items", lambda sid, items: calls.setdefault("added", items)
        )
        monkeypatch.setattr(pstore, "clear_session", lambda sid: calls.setdefault("cleared", sid))
        assert service.conversation_history("s1") == [{"role": "user"}]
        service.append_conversation("s1", [{"role": "assistant"}])
        service.clear_conversation("s1")
        assert calls["added"] == [{"role": "assistant"}]
        assert calls["cleared"] == "s1"


class TestMemoryTools:
    async def test_remember_recall_roundtrip_scoped_to_agent(self, swapped_singleton):
        tools.discover(force=True)
        remember = tools.get("memory.remember")
        recall = tools.get("memory.recall")
        identity = AIRunContext(user_id=uuid4(), role="teacher", agent_key="teacher_assistant")

        result = await tools.execute_tool(remember, identity, '{"text": "prefers MCQ", "key": "pref"}')
        assert result["remembered"] is True
        got = await tools.execute_tool(recall, identity, '{"query": "mcq"}')
        assert got[0]["text"] == "prefers MCQ" and got[0]["key"] == "pref"

        # a different agent key sees nothing (agent-scope isolation)
        other_agent = AIRunContext(user_id=identity.user_id, role="teacher", agent_key="grader")
        assert await tools.execute_tool(recall, other_agent, "{}") == []

    async def test_student_role_allowed(self, swapped_singleton):
        tools.discover(force=True)
        recall = tools.get("memory.recall")
        student = AIRunContext(user_id=uuid4(), role="student", agent_key="student_assistant")
        assert await tools.execute_tool(recall, student, "{}") == []


class TestContextEngineFacet:
    def test_agent_memory_provider_surfaces_memories(self, swapped_singleton):
        user = uuid4()
        swapped_singleton.remember_agent(user, "grader", {"text": "lenient on partial credit"})

        class Request:
            user_id = user
            agent_key = "grader"

        items = AgentMemoryProvider().collect(Request())
        assert len(items) == 1
        assert items[0].content["text"] == "lenient on partial credit"
        assert items[0].scope == "agent"

    def test_snapshot_has_memories_field(self):
        ctx = AgentExecutionContext(request_id="r", built_at=None, agent_key=None)
        assert ctx.memories == ()
