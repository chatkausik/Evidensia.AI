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
