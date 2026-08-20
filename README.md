# Evidensia AI

Evidensia is an autonomous research and evidence-intelligence platform. This build implements persistent local document ingestion, multi-source research-paper discovery, hierarchical chunking, hybrid retrieval, a corrective LangGraph research workflow, claim and citation verification, retrieval evaluation, and an interactive Research Studio.

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

The local API stores documents, research runs and event timelines, evaluation experiments, feedback, saved searches, and collections under `.evidensia_data` by default, so work survives API restarts. Set `EVIDENSIA_DATA_DIR` before starting the API to use a different location.

## Research-paper discovery

The **Discover papers** workspace searches arXiv, OpenAlex, Semantic Scholar, and Crossref over a bounded date range. These sources support basic discovery without credentials. OpenAlex and Semantic Scholar keys increase API capacity, while a contact email identifies Evidensia politely to scholarly APIs and enables Unpaywall open-access resolution:

```bash
export OPENALEX_API_KEY=your_key
export SEMANTIC_SCHOLAR_API_KEY=your_key
export EVIDENSIA_CONTACT_EMAIL=you@example.com
```

Discovery is metadata-first. Results are normalized, ranked, and deduplicated across providers. Selecting **Ingest selected** downloads trusted open-access PDFs from arXiv or an Unpaywall-resolved DOI when possible. Otherwise, Evidensia imports a clearly reported abstract fallback while preserving the repository or publisher URL.

API endpoints:

- `POST /v1/sources/discover` — search, normalize, rank, and deduplicate four scholarly sources
- `POST /v1/sources/import` — index selected discovery results
- `POST /v1/sources/compare` — compare methods, datasets, topics, citations, and access status
- `GET /v1/sources/{paper_id}/citation-graph` — retrieve Semantic Scholar references and citations
- `GET|POST /v1/saved-searches` — persist and rerun discovery queries
- `GET|POST /v1/collections` — scope research to curated document groups
- `GET /v1/research/{run_id}/export` — export Markdown, JSON, BibTeX, or RIS reports

## Configurable model providers

The default local providers are deterministic and require no credentials. Hosted embedding, reranking, and entailment services can be selected independently with the `EVIDENSIA_EMBEDDING_*`, `EVIDENSIA_RERANK_*`, and `EVIDENSIA_ENTAILMENT_*` variables shown in `.env.example`. `GET /v1/providers` reports the providers active in a running API instance.

## Implemented scope

- PDF, Markdown, HTML, and text ingestion
- arXiv, OpenAlex, Semantic Scholar, and Crossref discovery for recent AI papers
- Unpaywall resolution for DOI-linked open-access PDFs
- DOI/title/author deduplication and provenance-preserving abstract import
- section-aware parent and retrieval chunks
- deterministic metadata extraction
- local dense retrieval and BM25
- reciprocal-rank fusion and auditable reranking
- LangGraph planning, retrieval, sufficiency, correction, synthesis, and verification loop
- supporting and contradicting evidence with exact source spans
- citation validity and lexical entailment checks
- Recall@K, document recall, Precision@K, MRR, NDCG, hit rate, answer/claim coverage, and ablation APIs
- durable research runs, event streams, experiments, feedback, saved searches, and collections
- live Research Studio SSE, evidence explorer, source comparison, citation graph, retrieval debugger, and evaluation dashboard
- Markdown, JSON, BibTeX, and RIS report exports

The local index and deterministic research components are working development baselines. Provider seams are explicit so hosted embeddings, reranking, and entailment can be introduced independently without changing the API contracts. Production infrastructure and large-scale deployment remain deferred.
