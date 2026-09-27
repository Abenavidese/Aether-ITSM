"""
Fase 14.0 — the CI half of the RAG eval: the golden dataset points at
sections that really exist in the corpus, and the metrics compute what they
claim. The real run (embeddings + Postgres) is `python -m evals.rag.run`.
"""
import pytest

from evals.rag.corpus import MAIN_TENANT, OTHER_TENANT, load_corpus, load_dataset
from evals.rag.metrics import Hit, QueryResult, check_thresholds, hit_at, ndcg_at, reciprocal_rank, summarize
from src.rag.chunking import split_sections
from src.rag.parsing import parse_file

CATEGORIES = {"paraphrase", "exact_code", "keyword", "follow_up", "cross_lingual", "table", "no_answer"}


def _sections() -> dict[str, list[str]]:
    return {doc.filename: [s.title or "" for s in split_sections(parse_file(doc.path).text)]
            for doc in load_corpus() if doc.tenant_id == MAIN_TENANT}


def test_dataset_is_well_formed_and_targets_exist():
    cases = load_dataset()
    sections = _sections()
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["category"] for c in cases} == CATEGORIES
    assert sum(1 for c in cases if not c["targets"]) >= 10          # "no answer" must be measured
    for case in cases:
        assert (case["category"] == "no_answer") == (not case["targets"]), case["id"]
        for target in case["targets"]:
            assert target["file"] in sections, (case["id"], target["file"])
            assert any(hit_at([Hit(target["file"], s, MAIN_TENANT)], [target], 1) for s in sections[target["file"]]), \
                f"{case['id']}: section {target['section']!r} not in {target['file']}"


def test_corpus_has_a_second_tenant_for_leak_detection():
    tenants = {d.tenant_id for d in load_corpus()}
    assert tenants == {MAIN_TENANT, OTHER_TENANT}


def _h(file, section, tenant=MAIN_TENANT):
    return Hit(file, section, tenant)


def test_section_match_is_accent_and_case_insensitive():
    target = {"file": "a.md", "section": "Pérdida o cambio del teléfono con MFA"}
    assert hit_at([_h("a.md", "PERDIDA O CAMBIO DEL TELEFONO CON MFA")], [target], 1)
    assert not hit_at([_h("b.md", "Pérdida o cambio del teléfono con MFA")], [target], 1)
    assert not hit_at([_h("a.md", "")], [target], 1)


def test_rank_metrics():
    targets = [{"file": "a.md", "section": "X"}, {"file": "a.md", "section": "Y"}]
    hits = [_h("b.md", "Z"), _h("a.md", "X"), _h("a.md", "X"), _h("a.md", "Y")]
    assert reciprocal_rank(hits, targets) == pytest.approx(0.5)
    # X at rank 2 credited once (the duplicate at rank 3 is not), Y at rank 4.
    ideal = 1 + 1 / 1.5849625
    assert ndcg_at(hits, targets, 5) == pytest.approx((1 / 1.5849625 + 1 / 2.3219281) / ideal, rel=1e-4)


def test_summary_counts_leaks_and_no_answer():
    results = [
        QueryResult("a", "paraphrase", [{"file": "a.md", "section": "X"}], passages=[_h("a.md", "X")]),
        QueryResult("b", "no_answer", [], passages=[]),
        QueryResult("c", "no_answer", [], passages=[_h("z.md", "Q", OTHER_TENANT)]),
    ]
    summary = summarize(results, MAIN_TENANT)
    assert summary["hit@1"] == 1.0 and summary["no_answer_accuracy"] == 0.5 and summary["tenant_leaks"] == 1
    assert check_thresholds(summary, {"tenant_leaks_max": 0, "hit@1": 0.9}) == ["tenant_leaks=1 > 0"]
