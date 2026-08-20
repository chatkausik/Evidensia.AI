# Evidensia AI

Evidensia is an autonomous research and evidence-intelligence platform. This build implements local document ingestion, live research-paper discovery, hierarchical chunking, hybrid retrieval, a corrective LangGraph research workflow, claim and citation verification, retrieval evaluation, and an interactive Research Studio.

Phases 5 (production infrastructure) and 7 (large-scale deployment) from the source design are intentionally deferred.

## Quick start

```bash
python3 -m pip install -e '.[dev]'
uvicorn evidensia.api:app --port 8001 --reload
```

In a second terminal:

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000`. The API runs at `http://localhost:8001`, with interactive documentation at `/docs`.

The local API stores ingested documents under `.evidensia_data` by default, so the library survives API restarts. Set `EVIDENSIA_DATA_DIR` before starting the API to use a different location.

## Research-paper discovery

The **Discover papers** workspace searches arXiv and OpenAlex over a bounded date range. Both sources support basic discovery without credentials. For a higher OpenAlex usage budget, export a free API key before starting the API. A contact email identifies Evidensia politely to scholarly APIs:

```bash
export OPENALEX_API_KEY=your_key
export EVIDENSIA_CONTACT_EMAIL=you@example.com
```

Discovery is metadata-first. Selecting **Ingest selected** downloads and extracts arXiv PDFs into the local evidence index. For OpenAlex results or failed PDF downloads, Evidensia imports a clearly reported abstract fallback. It retains the original repository or publisher URL and does not serve copied PDFs to other users.

API endpoints:

- `POST /v1/sources/discover` — search, normalize, and deduplicate arXiv/OpenAlex results
- `POST /v1/sources/import` — index selected discovery results

## Implemented scope

- PDF, Markdown, HTML, and text ingestion
- arXiv and OpenAlex discovery for recent AI papers
- DOI/title/author deduplication and provenance-preserving abstract import
- section-aware parent and retrieval chunks
- deterministic metadata extraction
- local dense retrieval and BM25
- reciprocal-rank fusion and auditable reranking
- LangGraph planning, retrieval, sufficiency, correction, synthesis, and verification loop
- supporting and contradicting evidence with exact source spans
- citation validity and lexical entailment checks
- Recall@K, Precision@K, MRR, NDCG, hit rate, and ablation APIs
- Research Studio, evidence explorer, source library, retrieval debugger, and evaluation dashboard

The local index and deterministic research components are working development baselines. Provider seams are kept explicit so Pinecone, hosted embeddings/reranking, and model-backed agents can be introduced without changing the API contracts.
