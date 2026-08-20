# Evidensia Research Studio

The Research Studio is Evidensia's interactive web workspace for autonomous research, live paper discovery, source ingestion, evidence inspection, retrieval debugging, and evaluation.

## What the studio provides

- **Research** — submit a question, choose depth and scope, follow the live research timeline, and inspect verified claims and citations.
- **Discover papers** — search arXiv, OpenAlex, Semantic Scholar, and Crossref, then ingest selected open-access papers or explicit abstract fallbacks.
- **Source library** — review indexed documents and their extracted metadata.
- **Retrieval debugger** — compare dense, sparse, fused, and reranked evidence with transparent scores.
- **Evaluations** — run retrieval and claim-coverage experiments and inspect persisted results.

The full system diagram and execution details are in [Architecture and research flow](../../docs/ARCHITECTURE.md).

## Local development

Start the FastAPI service from the repository root:

```bash
python3 -m pip install -e '.[dev]'
cp .env.example .env
uvicorn evidensia.api:app --host 127.0.0.1 --port 8002 --reload --env-file .env
```

Then start the Studio:

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000`, or the next available port shown in the terminal.

## Configuration

`NEXT_PUBLIC_API_URL` selects the Evidensia API and defaults to `http://127.0.0.1:8002`. Copy `.env.example` when a different API origin is needed.

The hosted Studio is a frontend deployment and still needs a reachable Evidensia API for discovery, ingestion, research, and evaluation operations.

## Validation

```bash
npm run lint
npm run build
```

The application is built with vinext for Cloudflare-compatible deployment through Sites.
