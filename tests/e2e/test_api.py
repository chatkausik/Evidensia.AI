from fastapi.testclient import TestClient

from evidensia.api import create_app
from evidensia.connectors.arxiv import ArxivConnector


ARXIV_FEED = b"""<feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>https://arxiv.org/abs/2601.01234v1</id>
<updated>2026-01-31T12:00:00Z</updated><published>2026-01-30T12:00:00Z</published>
<title>Agentic Retrieval for Enterprise Questions</title>
<summary>We evaluate a multi-hop retrieval agent on enterprise question answering.</summary>
<author><name>Ada Researcher</name></author><category term="cs.AI" />
<link href="https://arxiv.org/abs/2601.01234v1" rel="alternate" />
</entry></feed>"""


def test_document_search_research_and_evaluation_flow() -> None:
    client = TestClient(create_app(seed_demo=False))
    upload = client.post(
        "/v1/documents",
        files={
            "file": (
                "benchmark.md",
                b"# Benchmark\nAuthors: Test Author\n2025\n\n## Results\nAgentic RAG improved HotpotQA Recall@10 from 78.0 to 89.0. However, latency doubled.",
                "text/markdown",
            )
        },
    )
    assert upload.status_code == 201, upload.text
    document = upload.json()
    assert document["status"] == "indexed"

    search = client.post("/v1/search/debug", json={"query": "HotpotQA Recall@10", "limit": 5})
    assert search.status_code == 200
    assert search.json()["reranked"][0]["chunk"]["document_id"] == document["document_id"]

    research = client.post(
        "/v1/research",
        json={
            "question": "Does agentic RAG improve HotpotQA and what is the latency trade-off?",
            "depth": "quick",
            "run_synchronously": True,
        },
    )
    assert research.status_code == 202, research.text
    assert research.json()["status"] == "completed"

    chunks = [item["chunk"]["chunk_id"] for item in search.json()["reranked"]]
    evaluation = client.post(
        "/v1/evals/run",
        json={
            "cases": [{"id": "case_1", "question": "HotpotQA Recall@10", "gold_chunks": [chunks[0]]}],
            "pipeline": "reranked",
            "k": 5,
        },
    )
    assert evaluation.status_code == 200
    assert evaluation.json()["metrics"]["recall_at_k"] == 1.0


def test_paper_discovery_and_import_flow() -> None:
    application = create_app(seed_demo=False)
    application.state.container.discovery.connectors["arxiv"] = ArxivConnector(fetch=lambda _: ARXIV_FEED)
    client = TestClient(application)

    discovery = client.post("/v1/sources/discover", json={
        "query": "agentic retrieval",
        "date_from": "2025-01-01",
        "date_to": "2026-08-20",
        "providers": ["arxiv"],
    })
    assert discovery.status_code == 200, discovery.text
    paper = discovery.json()["papers"][0]

    imported = client.post("/v1/sources/import", json={"paper_ids": [paper["paper_id"]]})
    assert imported.status_code == 201, imported.text
    assert imported.json()["imported"][0]["source_uri"] == paper["landing_url"]

    documents = client.get("/v1/documents")
    assert len(documents.json()) == 1


def test_persistent_workflows_scoped_research_and_exports(tmp_path) -> None:
    application = create_app(seed_demo=True, data_dir=str(tmp_path))
    client = TestClient(application)
    documents = client.get("/v1/documents").json()
    agentic = next(item for item in documents if item["document_id"] == "demo-agentic")

    saved = client.post("/v1/saved-searches", json={
        "name": "Recent agentic RAG",
        "query": "agentic RAG",
        "date_from": "2025-01-01",
        "date_to": "2026-12-31",
        "providers": ["arxiv", "openalex"],
    })
    assert saved.status_code == 201, saved.text

    collection = client.post("/v1/collections", json={
        "name": "Agentic evidence",
        "description": "Focused evaluation corpus",
        "document_ids": [agentic["document_id"]],
    })
    assert collection.status_code == 201, collection.text
    collection_id = collection.json()["collection_id"]

    research = client.post("/v1/research", json={
        "question": "What benefits and costs were measured for agentic retrieval?",
        "namespace": collection_id,
        "date_from": "2025-01-01",
        "date_to": "2025-12-31",
        "allowed_sources": ["demo://"],
        "depth": "quick",
        "run_synchronously": True,
    })
    assert research.status_code == 202, research.text
    payload = research.json()
    assert payload["metadata_filters"]["document_ids"] == ["demo-agentic"]
    assert {item["citation"]["document_id"] for item in payload["retrieved_evidence"]} == {"demo-agentic"}

    exported = client.get(f"/v1/research/{payload['run_id']}/export?format=markdown")
    assert exported.status_code == 200
    assert "## Sources" in exported.text

    evaluation = client.post("/v1/evals/run", json={"run_ablation": True, "dataset_name": "sample-v2"})
    assert evaluation.status_code == 200, evaluation.text
    assert len(evaluation.json()) == 4
    assert evaluation.json()[-1]["cases"] == 6
    assert {result["metadata"]["dataset_name"] for result in evaluation.json()} == {"sample-v2"}

    invalid_saved = client.post("/v1/saved-searches", json={
        "name": "Invalid range",
        "query": "agentic RAG",
        "date_from": "2026-12-31",
        "date_to": "2025-01-01",
        "providers": ["arxiv"],
    })
    assert invalid_saved.status_code == 422

    restarted = TestClient(create_app(seed_demo=False, data_dir=str(tmp_path)))
    assert restarted.get("/v1/saved-searches").json()[0]["search_id"] == saved.json()["search_id"]
    assert restarted.get(f"/v1/research/{payload['run_id']}").status_code == 200
    assert len(restarted.get("/v1/evals/experiments").json()) == 4
