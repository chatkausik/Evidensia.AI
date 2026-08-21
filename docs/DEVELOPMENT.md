# Development

## Layout

```text
src/evidensia/
  api.py              FastAPI boundary: 33 routes, SSE, CORS, provider manifest
  models.py           Pydantic domain models; StrictModel forbids extra fields
  providers.py        Provider protocols and environment-driven selection
  persistence.py      SQLite state store for runs, events, searches, collections
  agents/             Planner, evidence extraction, sufficiency, synthesis,
                      OpenAI structured reasoning
  connectors/         arXiv, OpenAlex, Semantic Scholar, Crossref, Unpaywall, HTTP
  evals/              Metrics and the ablation runner
  graph/research.py   LangGraph corrective-retrieval state machine
  ingestion/          Parser, hierarchical chunker, metadata extraction
  retrieval/          Query intent, dense + BM25 index, RRF fusion, reranking
  services/           Knowledge, research runs, discovery, memory, exports
apps/web/app/page.tsx The entire Research Studio
tests/                unit, integration, e2e, live
```

## Running the tests

```bash
pytest                                    # hermetic: no network, no credentials
pytest tests/unit -q
EVIDENSIA_LIVE_TESTS=1 pytest tests/live  # real provider calls — costs money
```

The default suite is offline by design and must stay that way. Anything needing
a credential or a network round trip belongs in `tests/live/`, behind the
`EVIDENSIA_LIVE_TESTS` gate.

### Why `tests/live/` exists

Every other test stubs the provider transport, so the request the provider
actually receives is never exercised. That is a real blind spot: a rejected
schema, a retired model id, or an invalid key surfaces only at runtime, gets
caught by the deterministic fallback, and produces a run that looks entirely
healthy while the model never executed.

Run the live suite after changing a schema, a model id, or the request shape.
It is the only thing that will tell you the request is still accepted.

## Import hygiene

`retrieval/__init__.py` resolves its re-exports lazily (PEP 562). `providers`
depends on `retrieval.text`, and importing any submodule executes the package
`__init__`; when that eagerly imported `hybrid` and `index` — which import
`providers` — the cycle closed and `import evidensia.providers` failed outright.

It only appeared to work because every entry point happened to import
`evidensia.retrieval` first, resolving the cycle from the other side.

Two rules follow:

- Import a type you only need for annotations under `TYPE_CHECKING`.
- After changing imports in `retrieval/` or `providers.py`, verify both
  directions:

```bash
python -c "import evidensia.providers"
python -c "import evidensia.retrieval; import evidensia.providers"
```

Both must succeed. Only testing the second hides the bug.

## Adding a provider

Providers are protocols in `providers.py`, selected by
`providers_from_environment()`. To add one:

1. Implement the relevant protocol (`EmbeddingProvider`, `RerankerProvider`,
   `EntailmentProvider`, or `ResearchReasoningProvider`).
2. Give it a descriptive `name` — it appears in `GET /v1/providers` and in every
   run's `provider_manifest`, and operators rely on it to tell hosted from local.
3. Wire it into `providers_from_environment()` behind its own environment
   variable, so it can be enabled independently of the others.
4. Fail soft: raise a recoverable error so the deterministic fallback engages
   rather than taking down the run.
5. Add a live test under `tests/live/` that exercises the real request.

Point 4 has a corollary that is easy to get wrong: **a fallback must be
observable.** Record it on `ResearchState.reasoning_fallbacks` and log the
exception itself, not just `type(exc).__name__` — otherwise a rejected schema,
an expired key, and a timeout are indistinguishable in production, and the
system reports success while running on heuristics.

## Adding a metric

Add the field to `MetricSet` in `models.py`, compute it in
`evals/runner.py:run()`, and surface it in the Studio's evaluations view. Keep
the four ablation arms comparable — a metric only one pipeline can produce
makes the comparison harder to read, not richer.

## Front end

```bash
cd apps/web
npm install
npm run dev          # http://localhost:3000
npx tsc --noEmit     # typecheck
npx eslint app       # lint
```

`app/page.tsx` holds the whole Studio: five views, all state in one component.
Known rough edges: `worker/index.ts` and `db/index.ts` are untouched Cloudflare
starter scaffolding and report type errors under `tsc` because
`@cloudflare/workers-types` is not installed. Those three errors predate the
application code; `app/page.tsx` itself should stay clean.

## Conventions

- Domain models inherit `StrictModel` (`extra="forbid"`), so an unexpected field
  is an error rather than silent data loss.
- Local, deterministic behaviour is the default everywhere. Hosted services are
  opt-in and must degrade to a local implementation rather than failing a run.
- Anything that spends money or touches an external account is opt-in and
  visible in `GET /v1/providers`.
