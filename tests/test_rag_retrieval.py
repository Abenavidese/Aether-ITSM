"""
Fase 14 — the knowledge base end to end on SQLite (the Python-scoring
fallback of src/rag/store.py; the Postgres SQL paths are covered by
tests/test_rls_postgres.py and the retrieval eval, evals/rag).

Embeddings are a deterministic bag-of-words hash, so similarity is real
(shared words -> closer) without a model.
"""
import hashlib
import json
import math
import uuid
from pathlib import Path

import httpx
import pytest
from fakes import empty_retrieval  # noqa: F401 — keeps the shared fakes importable here too

from src.rag import documents
from src.rag.citations import validate_citations
from src.rag.parsing import ParsedDocument, parse_file
from src.rag.query import is_follow_up, plan_query
from src.rag.rerank import ApiReranker, NoopReranker, RerankOutcome
from src.rag.retrieval import Passage, RetrievalConfig, _join_without_overlap
from src.rag.service import build_retriever
from src.rag.store import KnowledgeStore, bm25_rank
from src.rag.text import entity_in, extract_entities, fold, query_terms, to_tsquery

MODEL = "fake:bow"
DIM = 128


@pytest.fixture(autouse=True)
def _schema():
    # Other test files build it by importing src.main (which migrates); this
    # one must also pass when run on its own.
    from src.db import models
    from src.db.database import engine
    models.Base.metadata.create_all(bind=engine)


class BowEmbeddings:
    """Bag of folded words hashed into DIM buckets, L2-normalized."""

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIM
        for term in query_terms(text, limit=10_000):
            v[int(hashlib.md5(term.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


VPN = """# Política VPN

## Solicitud de acceso

El acceso VPN se pide con un ticket y lo aprueba el jefe directo. Para contratistas vence a los 90 días.

## Error ERR_VPN_809

ERR_VPN_809 indica que la red bloquea el puerto UDP 4500. Cambie a la red del celular.
"""

MFA = """# Contraseñas

## Bloqueo de cuenta

Tras 5 intentos fallidos la cuenta se bloquea durante 30 minutos.
"""

OTHER_TENANT_VPN = """# VPN de otra empresa

## Error ERR_VPN_809

En esta empresa ERR_VPN_809 significa certificado vencido.
"""


def _company(prefix: str) -> str:
    from src.db.database import SessionLocal
    from src.db.models import Company
    tenant = f"{prefix}-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Company(id=tenant, name=tenant))
    db.commit()
    db.close()
    return tenant


def _index(tenant: str, filename: str, text: str, source_type: str = "company_policy",
           embeddings=None, model: str = MODEL) -> documents.RegisterOutcome:
    outcome = documents.register_upload(tenant, None, filename, source_type, ParsedDocument(text=text))
    if not outcome.unchanged:
        assert documents.index_version(tenant, outcome.document_id, outcome.version,
                                       embeddings or BowEmbeddings(), model) == "ready"
    return outcome


def _retriever(max_distance: float = 0.75, reranker=None, **config):
    retriever = build_retriever(store=KnowledgeStore(), embeddings=BowEmbeddings(), model_id=MODEL,
                                reranker=reranker or NoopReranker())
    retriever.config = RetrievalConfig(max_distance=max_distance, **config)
    return retriever


@pytest.fixture
def kb():
    tenant, other = _company("kb"), _company("kb-other")
    _index(tenant, "vpn.md", VPN)
    _index(tenant, "mfa.md", MFA)
    _index(other, "vpn_otra.md", OTHER_TENANT_VPN)
    return tenant, other


SOURCES = ["company_policy", "technical_repo"]


# ── text utilities ────────────────────────────────────────────────────────────

def test_entities_and_terms():
    assert extract_entities("me sale ERR_VPN_809 y PAY-4012") == ["err_vpn_809", "pay-4012"]
    assert extract_entities("VITE_API_URL undefined en 10.20.3.15") == ["vite_api_url", "10.20.3.15"]
    assert extract_entities("¿cuántos caracteres?") == []
    assert query_terms("¿Cuántos caracteres debe tener mi CLAVE?") == ["caracteres", "tener", "clave"]
    assert entity_in("e-12", fold("Error E-12: tóner")) and not entity_in("e-12", fold("E-125"))


def test_tsquery_cannot_be_injected():
    terms = query_terms("vpn') | !x & (y:* <-> z; DROP TABLE")
    assert all(ch.isalnum() or ch in " |:*" for ch in to_tsquery(terms))


def test_bm25_prefers_rare_terms():
    from src.rag.store import StoredChunk

    def chunk(i):
        return StoredChunk(str(i), "d", 1, "f", "", None, i, "company_policy", "")
    candidates = [(chunk(1), "error error error general"), (chunk(2), "error kube cluster")]
    ranked = bm25_rank(candidates, ["error", "kube"], {"error": 50, "kube": 1}, 100)
    assert [c.id for c, _ in ranked] == ["2", "1"]


# ── query planning ────────────────────────────────────────────────────────────

def test_follow_up_detection():
    assert is_follow_up("¿y el de Admin?", ["¿Por cuánto tiempo me dan el rol Developer?"])
    assert is_follow_up("¿cuánto tiempo tengo que esperar?", ["mi cuenta se bloqueó"])
    assert not is_follow_up("¿y ERR_VPN_812?", ["hola"])            # names its own identifier
    assert not is_follow_up("¿y el de Admin?", [])                   # nothing to follow
    assert not is_follow_up("necesito instalar Docker Desktop en mi laptop nueva", ["hola"])


def test_concat_rewrite_uses_previous_message():
    plan = plan_query("¿y el de Admin?", ["¿Por cuánto tiempo me dan el rol Developer en AWS?"])
    assert plan.rewritten and plan.mode == "concat"
    assert "Developer" in plan.semantic and "admin" in plan.terms and "developer" in plan.terms


def test_llm_rewrite_that_adds_facts_is_rejected():
    history = ["la impresora del piso 3 muestra E-12"]
    invented = plan_query("¿y qué hago?", history, mode="llm",
                          rewriter=lambda h, q: "cómo reinicio la VPN de FortiClient")
    assert invented.mode == "concat" and "rejected" in invented.notes[0]
    grounded = plan_query("¿y qué hago?", history, mode="llm",
                          rewriter=lambda h, q: "qué hago si la impresora del piso 3 muestra E-12")
    assert grounded.mode == "llm"


# ── retrieval ─────────────────────────────────────────────────────────────────

def test_exact_code_is_found_and_numbered(kb):
    tenant, _ = kb
    result = _retriever().retrieve(tenant, "me sale ERR_VPN_809", sources=SOURCES)
    assert result.passages and result.passages[0].section == "Error ERR_VPN_809"
    assert result.passages[0].n == 1
    prompt = result.to_prompt()
    assert prompt.startswith("[1] vpn.md — Sección: Error ERR_VPN_809")
    assert "Documento:" not in prompt   # the chunk header is rebuilt as the passage label


def test_other_tenants_documents_never_come_back(kb):
    tenant, other = kb
    result = _retriever(max_distance=2.0).retrieve(tenant, "ERR_VPN_809 certificado vencido", sources=SOURCES)
    assert result.passages and all(p.filename != "vpn_otra.md" for p in result.passages)
    assert all(c.chunk.filename != "vpn_otra.md" for c in result.candidates)
    theirs = _retriever(max_distance=2.0).retrieve(other, "ERR_VPN_809", sources=SOURCES)
    assert {p.filename for p in theirs.passages} == {"vpn_otra.md"}


def test_unrelated_question_returns_nothing(kb):
    tenant, _ = kb
    result = _retriever(max_distance=0.6).retrieve(tenant, "menú del comedor de esta semana", sources=SOURCES)
    assert result.empty and result.to_prompt() == ""


def test_unknown_identifier_raises_the_bar(kb):
    tenant, _ = kb
    retriever = _retriever(max_distance=0.95, entity_miss_distance_margin=0.9)
    assert retriever.retrieve(tenant, "error KUBE-7731 en el cluster de la VPN", sources=SOURCES).empty


def test_follow_up_retrieves_what_it_means(kb):
    tenant, _ = kb
    retriever = _retriever(max_distance=0.8)
    alone = retriever.retrieve(tenant, "¿y para un contratista?", sources=SOURCES)
    followed = retriever.retrieve(tenant, "¿y para un contratista?", sources=SOURCES,
                                  history=["¿Cómo pido acceso a la VPN?"])
    assert not alone.plan.rewritten and followed.plan.rewritten
    assert followed.passages[0].section == "Solicitud de acceso"


def test_source_filter(kb):
    tenant, _ = kb
    assert _retriever(max_distance=2.0).retrieve(tenant, "VPN", sources=["technical_repo"]).empty


class _FailingReranker:
    name = "broken"

    def rerank(self, query, passages):
        return RerankOutcome(None, "error: RuntimeError")


class _ReverseReranker:
    name = "reverse"

    def rerank(self, query, passages):
        return RerankOutcome([float(i) for i in range(len(passages))], "ok")


def test_reranker_failure_keeps_hybrid_order(kb):
    tenant, _ = kb
    plain = _retriever().retrieve(tenant, "ERR_VPN_809", sources=SOURCES)
    broken = _retriever(reranker=_FailingReranker()).retrieve(tenant, "ERR_VPN_809", sources=SOURCES)
    assert broken.rerank_reason.startswith("error")
    assert [p.chunk_ids for p in broken.passages] == [p.chunk_ids for p in plain.passages]


def test_reranker_scores_reorder_and_gate(kb):
    tenant, _ = kb
    result = _retriever(reranker=_ReverseReranker(), min_rerank_score=0.5).retrieve(
        tenant, "acceso VPN contratista", sources=SOURCES)
    scores = [c.rerank for c in result.candidates]
    assert scores == sorted(scores, reverse=True)
    assert all(p.score >= 0.5 for p in result.passages)


def test_api_reranker_parses_cohere_shape_and_degrades():
    def handler(request):
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer k" and body["query"] == "q"
        return httpx.Response(200, json={"results": [{"index": 1, "relevance_score": 0.9},
                                                     {"index": 0, "relevance_score": 0.1}]})
    ok = ApiReranker("m", "https://rerank.test/v1/rerank", "k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert ok.rerank("q", ["a", "b"]).scores == [0.1, 0.9]
    down = ApiReranker("m", "https://rerank.test/v1/rerank", "k",
                       client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    outcome = down.rerank("q", ["a"])
    assert outcome.scores is None and outcome.reason.startswith("error")


# ── document lifecycle ────────────────────────────────────────────────────────

def test_same_content_is_not_reindexed(kb):
    tenant, _ = kb
    again = documents.register_upload(tenant, None, "vpn.md", "company_policy", ParsedDocument(text=VPN))
    assert again.unchanged and again.version == 1


def test_previous_version_answers_until_the_new_one_is_ready(kb):
    tenant, _ = kb
    retriever = _retriever(max_distance=2.0)
    v2 = documents.register_upload(tenant, None, "mfa.md", "company_policy",
                                   ParsedDocument(text=MFA.replace("30 minutos", "45 minutos")))
    assert v2.version == 2 and not v2.unchanged
    during = retriever.retrieve(tenant, "cuenta bloqueada intentos", sources=SOURCES)
    assert "30 minutos" in during.to_prompt()
    assert documents.index_version(tenant, v2.document_id, 2, BowEmbeddings(), MODEL) == "ready"
    after = retriever.retrieve(tenant, "cuenta bloqueada intentos", sources=SOURCES)
    assert "45 minutos" in after.to_prompt() and "30 minutos" not in after.to_prompt()


def test_a_superseded_job_does_not_activate_old_content(kb):
    tenant, _ = kb
    v2 = documents.register_upload(tenant, None, "mfa.md", "company_policy", ParsedDocument(text=MFA + "\nv2"))
    documents.register_upload(tenant, None, "mfa.md", "company_policy", ParsedDocument(text=MFA + "\nv3"))
    assert documents.index_version(tenant, v2.document_id, 2, BowEmbeddings(), MODEL) == "superseded"


def test_other_embedding_models_are_never_compared(kb):
    tenant, _ = kb

    class OtherModel(BowEmbeddings):
        def _vec(self, text):
            return [1.0] + [0.0] * 15          # other dimension, other space

    _index(tenant, "otro_modelo.md", "# Otro\n\n## Impresoras\n\nLa impresora del piso 3 usa la cola IMP-P3.",
           embeddings=OtherModel(), model="fake:other")
    result = _retriever(max_distance=2.0).retrieve(tenant, "impresora piso 3", sources=SOURCES)
    dense_ids = {c.chunk.id for c in result.candidates if c.distance is not None}
    otro = {c.chunk.id for c in result.candidates if c.chunk.filename == "otro_modelo.md"}
    assert otro and not (otro & dense_ids)     # found by keyword only, never by a cross-model distance
    assert documents.reindex_stale(tenant, MODEL) == 1


def test_feedback_is_searchable_only_after_approval(kb):
    tenant, _ = kb
    outcome = documents.register_feedback(tenant, "u1", "IT-9", "Para ERR_VPN_809 usar TCP 443.")
    assert outcome.status == "pending_review"
    assert _retriever(max_distance=2.0).retrieve(tenant, "ERR_VPN_809 TCP 443", sources=["ai_feedback"]).empty
    assert documents.review_feedback(tenant, outcome.document_id, "u2", approve=True) == "queued"
    assert documents.index_version(tenant, outcome.document_id, 1, BowEmbeddings(), MODEL) == "ready"
    found = _retriever(max_distance=2.0).retrieve(tenant, "ERR_VPN_809 TCP 443", sources=["ai_feedback"])
    assert found.passages and "corrección aprobada" in found.to_prompt()


def test_failed_indexing_is_reported(kb):
    tenant, _ = kb
    v = documents.register_upload(tenant, None, "roto.md", "company_policy", ParsedDocument(text="# X\n\ncontenido"))
    documents.mark_failed(tenant, v.document_id, v.version, "embedding service unreachable")
    view = {d["filename"]: d for d in documents.list_documents(tenant, MODEL)}["roto.md"]
    assert view["status"] == "failed" and "unreachable" in view["error"]


# ── assembly and citations ────────────────────────────────────────────────────

def test_overlapping_chunks_merge_without_duplication():
    left = "uno dos tres cuatro cinco seis siete ocho nueve diez once doce"
    right = "siete ocho nueve diez once doce trece catorce"
    assert _join_without_overlap(left, right) == left + " trece catorce"


def _passage(n: int) -> Passage:
    return Passage(n=n, document_id=f"d{n}", filename=f"f{n}.md", section="S", page=None,
                   source_type="company_policy", text="t", score=1.0, chunk_ids=[str(n)])


def test_invented_citations_are_removed_and_only_cited_sources_returned():
    report = validate_citations("Requiere aprobación [2]. Dura 30 días [7].", [_passage(1), _passage(2)])
    assert report.text == "Requiere aprobación [2]. Dura 30 días."
    assert report.removed == [7] and [s["n"] for s in report.sources] == [2]
    assert report.stats(2) == {"passages": 2, "cited": 1, "attributed": 0, "removed": 1,
                               "uncited_with_context": False}


def test_uncited_passages_are_attributed_only_on_evidence():
    from src.rag.citations import attribute

    vpn = _passage(1)
    vpn.text = ("ERR_VPN_809: la red bloquea el puerto UDP 4500. Cambie a la red del celular; en FortiClient "
                "active Usar TCP 443; si persiste, cierre sesión para renovar el certificado.")
    other = _passage(2)
    other.text = "El rol Admin se otorga por un máximo de 8 horas."
    question = "¿y si ya probé con el hotspot?"
    answer = "Active Usar TCP 443 en FortiClient y cierre sesión para renovar el certificado."
    assert attribute(answer, question, [vpn, other]) == [1]
    # Echoing the question proves nothing; an unrelated answer attributes nothing.
    assert attribute("Me sale ERR_VPN_809.", "me sale ERR_VPN_809", [vpn]) == []
    assert attribute("No tengo esa información.", "¿cuántos días de vacaciones tengo?", [other]) == []
    report = validate_citations(answer, [vpn, other], question=question)
    assert [s["n"] for s in report.sources] == [1] and report.attributed == [1] and report.cited == []


# ── parsing ───────────────────────────────────────────────────────────────────

def test_pdf_keeps_headings_tables_and_reports_scanned_pages():
    pdf = Path(__file__).resolve().parents[1] / "evals" / "rag" / "corpus" / "main" / "manual_impresoras.pdf"
    parsed = parse_file(pdf)
    assert "## Impresoras por piso" in parsed.text
    assert "| 3 | Ricoh IM C3000 | 10.20.3.15 | IMP-P3-OPERACIONES |" in parsed.text
    assert parsed.pages == 3 and "3" in parsed.warnings[0]


# ── service: tracing, query log, degradation ─────────────────────────────────

def test_retrieve_records_span_and_query_log(kb):
    import asyncio

    from src.db.database import SessionLocal
    from src.db.models import RagQueryLog
    from src.observability.tracing import trace_scope
    from src.rag import service

    tenant, _ = kb

    async def run():
        async with trace_scope("t:rag", "chat", tenant, persist=False) as trace:
            service.retrieve(tenant, "me sale ERR_VPN_809 password: Hunter2!", sources=SOURCES,
                             retriever=_retriever())
            return trace
    trace = asyncio.run(run())
    span = next(s for s in trace.spans if s.kind == "retrieval")
    assert span.attributes["passages"] and "stages_ms" in span.attributes
    db = SessionLocal()
    try:
        row = db.query(RagQueryLog).filter_by(tenant_id=tenant).one()
        assert row.passages >= 1 and "Hunter2" not in row.query   # redacted before it's stored
    finally:
        db.close()


def test_retrieval_failure_degrades_to_empty_context(kb):
    from src.rag import service

    tenant, _ = kb

    class Broken:
        def retrieve(self, *a, **kw):
            raise RuntimeError("database unreachable")
    result = service.retrieve(tenant, "VPN", sources=SOURCES, retriever=Broken())
    assert result.empty


def test_every_job_kind_has_a_handler():
    from src.services.job_registry import handlers
    all_handlers, dead = handlers()
    assert "index_document" in all_handlers and "index_document" in dead
