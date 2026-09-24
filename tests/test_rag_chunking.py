"""
Unit tests for contextual chunking (src/rag/chunking.py), the task-prefix
embeddings wrapper, and the relevance cutoff in retrieve_context — no
Ollama, no Postgres.
"""
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from src.rag.chunking import CHUNKER_VERSION, chunk_document, split_sections
from src.rag.embeddings import TaskPrefixedEmbeddings, _with_task_prefixes

POLICY_DOC = """GUÍA DE POLÍTICAS DE TI — VERTEX DYNAMICS S.A.S.

Política de acceso a VPN

Cualquier empleado puede solicitar el reinicio de su propia sesión de VPN.

Política de software estándar (MDM)

Docker Desktop (pkg_docker) está pre-aprobado.
Procedimiento:
1. Confirmar la lista blanca.
"""

SETEXT_DOC = """HOW TO BUY SOMETHING
----------------------
1. Click "Add to cart".

TROUBLESHOOTING
===============
- "Invalid credentials": re-check the email.
"""


def test_detects_standalone_and_parenthesized_headings():
    titles = [s.title for s in split_sections(POLICY_DOC)]
    assert titles == [
        "GUÍA DE POLÍTICAS DE TI — VERTEX DYNAMICS S.A.S.",
        "Política de acceso a VPN",
        "Política de software estándar (MDM)",
    ]


def test_detects_setext_and_markdown_headings():
    assert [s.title for s in split_sections(SETEXT_DOC)] == ["HOW TO BUY SOMETHING", "TROUBLESHOOTING"]
    assert [s.title for s in split_sections("# Intro\n\ntext\n\n## Setup\n\nmore\n")] == ["Intro", "Setup"]


def test_prose_and_list_lines_are_not_headings():
    titles = [s.title for s in split_sections(POLICY_DOC)]
    assert "Procedimiento:" not in titles
    assert not any(t and t.startswith("1.") for t in titles)


def test_every_chunk_carries_document_and_section_header():
    chunks = chunk_document(POLICY_DOC, "politicas.txt", base_metadata={"tenant_id": "t1"})
    mdm = next(c for c in chunks if "pkg_docker" in c.page_content)
    assert mdm.page_content.startswith(
        "Documento: politicas.txt — GUÍA DE POLÍTICAS DE TI — VERTEX DYNAMICS S.A.S.\n"
        "Sección: Política de software estándar (MDM)\n\n"
    )
    assert mdm.metadata["tenant_id"] == "t1"
    assert mdm.metadata["section"] == "Política de software estándar (MDM)"
    assert mdm.metadata["chunker"] == CHUNKER_VERSION


def test_chunks_never_mix_two_sections():
    chunks = chunk_document(POLICY_DOC, "politicas.txt")
    vpn = next(c for c in chunks if c.metadata["section"] == "Política de acceso a VPN")
    assert "pkg_docker" not in vpn.page_content


def test_pdf_chunks_keep_their_page():
    page1 = "Intro\n\n" + "a " * 700
    page2 = "Anexo\n\nContenido del anexo."
    text = page1 + "\n\n" + page2
    chunks = chunk_document(text, "doc.pdf", page_offsets=[(0, 1), (len(page1) + 2, 2)])
    assert next(c for c in chunks if "anexo." in c.page_content).metadata["page"] == 2
    assert chunks[0].metadata["page"] == 1


class _EchoEmbeddings(Embeddings):
    def __init__(self):
        self.seen: list[str] = []

    def embed_documents(self, texts):
        self.seen.extend(texts)
        return [[0.0] for _ in texts]

    def embed_query(self, text):
        self.seen.append(text)
        return [0.0]


def test_nomic_gets_task_prefixes_and_other_models_do_not():
    inner = _EchoEmbeddings()
    wrapped = _with_task_prefixes(inner, "nomic-embed-text:latest")
    assert isinstance(wrapped, TaskPrefixedEmbeddings)
    wrapped.embed_documents(["doc"])
    wrapped.embed_query("q")
    assert inner.seen == ["search_document: doc", "search_query: q"]

    assert _with_task_prefixes(inner, "text-embedding-3-small") is inner


def test_retrieve_context_drops_chunks_beyond_max_distance(monkeypatch):
    from src.rag import service

    class _FakeStore:
        def similarity_search_with_score(self, query, k, filter):
            return [(Document(page_content="relevant"), 0.2), (Document(page_content="noise"), 0.9)]

    monkeypatch.setattr(service, "get_vector_store", lambda: _FakeStore())
    context = service.retrieve_context("t1", "q")
    assert "relevant" in context and "noise" not in context
