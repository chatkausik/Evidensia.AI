# API reference

All 33 endpoints exposed by `src/evidensia/api.py`. Interactive documentation
generated from the same source is served at
[`/docs`](http://127.0.0.1:8002/docs) while the API is running, and the raw
schema at `/openapi.json`.

Base URL in local development: `http://127.0.0.1:8002`.

There is no authentication. The API binds to `127.0.0.1` and is intended for
single-user local research; do not expose it on a shared interface as-is.

## Health and configuration

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness. Returns `{status, version}` without touching the corpus. |
| `GET` | `/ready` | Readiness plus corpus size and the resolved provider manifest. |
| `GET` | `/metrics` | Prometheus text format: document count, run count, completed runs. |
| `GET` | `/v1/providers` | Which embedding, reranker, entailment, research, and memory providers are active. |

`/ready` is the fastest way to confirm what a running instance is actually
configured with:

```bash
curl -s http://127.0.0.1:8002/ready | python3 -m json.tool
```

```json
{
  "status": "ready",
  "details": {
    "documents": 106,
    "chunks": 1505,
    "persistent_library": true,
    "providers": {
      "embedding": "hashed-384",
      "reranker": "lexical-transparent-v1",
      "entailment": "lexical-overlap-v1",
      "research": "openai:gpt-5.4-mini",
      "memory": "mem0:platform"
    }
  }
}
```

A provider named `deterministic-fallback`, `hashed-384`, or `lexical-*` is a
local implementation, not a hosted one. See
[Provider configuration](CONFIGURATION.md).

## Documents

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/documents` | Upload a PDF, Markdown, HTML, or text file (multipart, 25 MB cap). |
| `GET` | `/v1/documents` | List indexed documents. |
| `GET` | `/v1/documents/{document_id}` | Fetch one document record. |
| `DELETE` | `/v1/documents/{document_id}` | Remove a document and its chunks. |
| `POST` | `/v1/documents/{document_id}/reindex` | Re-parse and re-chunk from the stored original. |

Upload returns `201` with the parsed metadata and chunk count. A document whose
text cannot be extracted returns `422` rather than indexing an empty record.

```bash
curl -X POST http://127.0.0.1:8002/v1/documents \
  -F "file=@paper.pdf;type=application/pdf" \
  -F "source_uri=https://arxiv.org/abs/2601.01234"
```

## Retrieval

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/search` | Ranked chunks for a query. |
| `POST` | `/v1/search/debug` | Every pipeline stage: dense, sparse, fused, reranked, plus query intent and timing. |

`/v1/search/debug` is what the Retrieval debugger renders. It returns each stage
separately so a ranking decision can be attributed to a specific component
rather than inferred from the final order.

```bash
curl -s -X POST http://127.0.0.1:8002/v1/search/debug \
  -H 'Content-Type: application/json' \
  -d '{"query":"multi-round RAG stopping criteria","limit":8}'
```

## Paper discovery

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/sources/discover` | Search arXiv, OpenAlex, Semantic Scholar, and Crossref over a date range. |
| `POST` | `/v1/sources/import` | Index selected discovery results. |
| `POST` | `/v1/sources/compare` | Compare methods, datasets, topics, citations, and access status across papers. |
| `GET` | `/v1/sources/{paper_id}/citation-graph` | Semantic Scholar references and citations. |
| `GET`/`POST` | `/v1/saved-searches` | Persist discovery queries. |
| `DELETE` | `/v1/saved-searches/{search_id}` | Remove a saved search. |
| `POST` | `/v1/saved-searches/{search_id}/run` | Re-run a saved search. |

Discovery is metadata-first: results are normalized, ranked, and deduplicated
across providers before anything is downloaded. Import fetches a trusted
open-access PDF where one exists (arXiv, or an Unpaywall-resolved DOI) and
otherwise indexes an abstract fallback, reported explicitly in the response's
`abstract_fallbacks` list rather than silently substituted.

Import only works for papers discovered in the same process lifetime — the
discovery cache is in memory. Restarting the API between discovering and
importing returns those ids under `missing`.

## Research runs

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/research` | Start a run. `run_synchronously: true` blocks; otherwise it runs in the background. |
| `GET` | `/v1/research` | List runs, newest first. |
| `GET` | `/v1/research/{run_id}` | Full run state including claims and the final report. |
| `GET` | `/v1/research/{run_id}/evidence` | Retrieved evidence spans. |
| `GET` | `/v1/research/{run_id}/events` | Agent events; `?stream=true` for Server-Sent Events. |
| `GET` | `/v1/research/{run_id}/diagnostics` | Whether the model path actually ran. |
| `GET` | `/v1/research/{run_id}/export` | Markdown, JSON, BibTeX, or RIS. |
| `POST` | `/v1/research/{run_id}/feedback` | Attach reviewer feedback to a run. |

### Streaming a run

`?stream=true` emits SSE frames with an `event:` type and an `id:`. The `id` is
a cursor: reconnecting with a `Last-Event-ID` header resumes after it rather
than replaying the run.

```bash
curl -N "http://127.0.0.1:8002/v1/research/${RUN_ID}/events?stream=true"
```

Event types, in the order a successful run emits them:

| Event | Meaning |
|---|---|
| `research.started` | Run accepted |
| `plan.created` | Question decomposed into sub-questions |
| `retrieval.completed` | One retrieval cycle finished |
| `evidence.assessed` | Coverage, diversity, and contradiction coverage scored |
| `retrieval.retry` | Sufficiency gate failed; queries rewritten (may repeat) |
| `synthesis.started` | Claims being built |
| `memory.stored` | Verified summary queued to Mem0 (only when memory is enabled) |
| `research.completed` | Citations verified, report composed |
| `research.failed` | Run aborted; `error` carries the reason |

### Run diagnostics

Every model-backed stage falls back to a deterministic implementation on
failure, which keeps a run alive when a provider is unavailable. The hazard is
that a fallback is otherwise **indistinguishable from success**: the run
completes, the report renders, and `provider_manifest` still names the
configured model, because it records what is *configured*, not what *ran*.

`GET /v1/research/{run_id}/diagnostics` separates the three cases:

```json
{
  "run_id": "run_37511f33c4134461",
  "reasoning_configured": "openai:gpt-5.4-mini",
  "served_by": "degraded",
  "degraded_stages": ["report", "synthesis", "verification"],
  "reasoning_fallbacks": ["synthesis: ResearchModelError: OpenAI returned HTTP 400"],
  "model_backed": false
}
```

| `served_by` | Meaning |
|---|---|
| `none` | No reasoning provider configured. Deterministic by design. |
| `degraded` | One is configured, but its calls failed. `reasoning_fallbacks` carries the causes. |
| `model` | Configured, and it served every stage. |

Check this after any run you intend to cite. `served_by: degraded` means the
report was produced by lexical heuristics regardless of what the manifest says.

## Evaluation

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/evals/run` | Score gold cases; `run_ablation: true` runs all four pipelines. |
| `GET` | `/v1/evals/experiments` | Stored experiment history. |
| `GET` | `/v1/evals/gold` | The bundled gold cases. |

See [Evaluation](EVALUATION.md) for metric definitions and methodology.

## Collections

| Method | Path | Purpose |
|---|---|---|
| `GET`/`POST` | `/v1/collections` | Curated document groups. |
| `DELETE` | `/v1/collections/{collection_id}` | Remove a collection. |

Passing a collection's id as `namespace` on `POST /v1/research` restricts
retrieval to that collection's documents.
