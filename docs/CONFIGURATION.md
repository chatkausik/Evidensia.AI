# Configuration

Every environment variable the code reads, what it defaults to, and what
changes when you set it. Copy `.env.example` to `.env` and pass it with
`--env-file .env`; nothing loads `.env` implicitly.

```bash
cp .env.example .env
uvicorn evidensia.api:app --host 127.0.0.1 --port 8002 --reload --env-file .env
```

Forgetting `--env-file` is a quiet failure, not a loud one: the API starts
normally and every optional provider silently resolves to its local
deterministic implementation. Confirm with `GET /v1/providers`.

## Core

| Variable | Default | Effect |
|---|---|---|
| `EVIDENSIA_DATA_DIR` | `.evidensia_data` | Where documents, SQLite state, runs, and experiments live. Not in `.env.example`; set it in the shell or add it. |
| `EVIDENSIA_CORS_ORIGINS` | local dev origins | Comma-separated extra browser origins, added to the built-in defaults. |
| `EVIDENSIA_CONTACT_EMAIL` | unset | Identifies Evidensia to scholarly APIs and enables Unpaywall open-access resolution. Scholarly providers ask for this; setting it is polite and raises rate limits. |

## Reasoning (OpenAI)

Setting `OPENAI_API_KEY` switches planning, claim synthesis, claim
verification, and report composition from deterministic heuristics to the
OpenAI Responses API. Leave it unset for a fully offline run.

| Variable | Default | Effect |
|---|---|---|
| `OPENAI_API_KEY` | unset | Enables the research provider. Without it, `served_by` is `none`. |
| `EVIDENSIA_OPENAI_MODEL` | `gpt-5.4-mini` | Research model id. |
| `EVIDENSIA_OPENAI_BASE_URL` | `https://api.openai.com/v1` | Must be HTTPS, except a localhost endpoint for testing. |
| `EVIDENSIA_OPENAI_REASONING_EFFORT` | `low` | One of `none`, `low`, `medium`, `high`, `xhigh`. Invalid values raise at startup. |
| `EVIDENSIA_OPENAI_TIMEOUT` | `45` | Seconds; must be in (0, 300]. |
| `EVIDENSIA_OPENAI_MAX_OUTPUT_TOKENS` | `3000` | Must be in [200, 20000]. |

**Cost**: with a key set, every research run makes several model calls. Runs are
not free; check `GET /v1/research/{run_id}/diagnostics` afterwards to confirm
the calls actually landed rather than falling back.

## Retrieval providers

The defaults are deterministic, need no credentials, and run offline. Each
hosted service is opted into independently — configuring embeddings does not
require configuring reranking.

| Variable group | Default provider | Effect when set |
|---|---|---|
| `EVIDENSIA_EMBEDDING_URL`, `_API_KEY`, `_MODEL` | `hashed-384` | Replaces hashed vectors with a hosted embedding endpoint. |
| `EVIDENSIA_RERANK_URL`, `_API_KEY`, `_MODEL` | `lexical-transparent-v1` | Replaces token-overlap reranking with a hosted cross-encoder. |
| `EVIDENSIA_ENTAILMENT_URL`, `_API_KEY`, `_MODEL` | `lexical-overlap-v1` | Replaces lexical entailment with a hosted NLI service. |

### What `hashed-384` actually is

The default embedding is a hashing-trick bag-of-words: tokens and adjacent
bigrams hashed into 384 buckets and L2-normalized. It is deterministic, free,
and instant — and it carries **no semantic knowledge whatsoever**. Two
paraphrases that share no tokens have a cosine similarity of zero.

This matters for how you read results. On queries that quote source text
closely it performs well, because exact-token overlap is exactly what it
captures. On a naturally-phrased research question it degrades sharply. See
[Evaluation](EVALUATION.md) for the measured difference.

## Long-term memory (Mem0)

| Variable | Default | Effect |
|---|---|---|
| `MEM0_API_KEY` | unset | Enables recall before planning and verified write-back after successful runs. |
| `EVIDENSIA_MEM0_HOST` | Mem0 default | Self-hosted Mem0 endpoint. |
| `EVIDENSIA_MEM0_TOP_K` | `5` | Memories recalled per run. |
| `EVIDENSIA_MEM0_THRESHOLD` | `0.2` | Minimum relevance to recall. |
| `EVIDENSIA_MEM0_TIMEOUT` | `5` | Seconds before giving up on Mem0. |

Memory is user-scoped: the Research Studio generates a browser-local researcher
id and sends it as `user_id`. Set `use_memory: false` on `POST /v1/research` to
opt a run out.

Recalled memories reach the planner only, framed as unverified personalization
context. They never enter the evidence set, claims, or citation verification.
Mem0 is fail-open: a missing key, a timeout, or a provider error leaves the
research workflow fully operational.

**Enabling `MEM0_API_KEY` writes to an external account.** Verified run
summaries are queued for write-back on success. That is real external state,
outside `EVIDENSIA_DATA_DIR`, and it persists after the local corpus is deleted.

## Scholarly discovery

| Variable | Default | Effect |
|---|---|---|
| `OPENALEX_API_KEY` | unset | Higher OpenAlex rate limits. |
| `SEMANTIC_SCHOLAR_API_KEY` | unset | Higher Semantic Scholar limits; also used for citation graphs. |

All four discovery sources work without credentials. Keys raise capacity.

## Web application

`apps/web/.env.example` holds the front-end configuration. Vite inlines
`NEXT_PUBLIC_*` at build time, so changing either requires restarting the dev
server.

| Variable | Default | Effect |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8002` | Where the Studio sends every request. |
| `NEXT_PUBLIC_SITE_URL` | `http://localhost:3000` | Canonical site URL for metadata. |

The default is **port 8002**. Starting the API on any other port without also
setting `NEXT_PUBLIC_API_URL` produces "The paper discovery API is unavailable"
in the browser while `curl` against the API succeeds — the UI is simply asking a
different address. See [Troubleshooting](TROUBLESHOOTING.md).

## Secrets

`.env` is gitignored and must stay that way. It holds live provider credentials.

- Never commit it, and never paste its contents into an issue or a log.
- `.env.example` is the tracked template and must contain only empty values.
- If a key has been exposed, rotate it at the provider rather than deleting the
  commit — a pushed secret should be assumed captured.

Verify before pushing:

```bash
git check-ignore -v .env        # must print a .gitignore rule
git log --all --name-only | grep -c '^\.env$'   # must be 0
```
