# Troubleshooting

Failures that have actually occurred while running this project, with the
diagnostic that distinguishes each from its look-alikes.

## "The paper discovery API is unavailable"

The browser reports the API is down while `curl` against it succeeds.

Almost always a **port mismatch**, not an outage. The Studio's default is
`http://127.0.0.1:8002`; an API started on any other port is invisible to it.

```bash
# What the browser is actually asking:
grep -n "const API_BASE" apps/web/app/page.tsx

# Is anything there?
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8002/health
```

Fix by starting the API on 8002, or point the Studio elsewhere with
`NEXT_PUBLIC_API_URL` in `apps/web/.env.local` and restart the dev server —
Vite inlines that value at build time, so an already-running server will not
pick it up.

If the port is right, check CORS by simulating the browser's preflight:

```bash
curl -s -i -X OPTIONS http://127.0.0.1:8002/v1/sources/discover \
  -H 'Origin: http://localhost:3000' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type' | head -5
```

A missing `access-control-allow-origin` means the origin needs adding via
`EVIDENSIA_CORS_ORIGINS`.

## A run completes but the report looks mechanical

The reasoning model probably never ran. Every model-backed stage falls back to
a deterministic implementation on failure, so a broken provider yields a
complete, plausible-looking run.

```bash
curl -s http://127.0.0.1:8002/v1/research/${RUN_ID}/diagnostics | python3 -m json.tool
```

| `served_by` | What happened |
|---|---|
| `none` | No `OPENAI_API_KEY`. Deterministic by design. |
| `degraded` | A provider is configured but failing. Read `reasoning_fallbacks`. |
| `model` | The model served every stage. |

`provider_manifest` alone cannot answer this — it records what is configured,
not what ran.

The most common cause of `degraded` is a `.env` that was never loaded. Nothing
reads `.env` implicitly; it must be passed with `--env-file .env`.

## `import evidensia.providers` raises ImportError

Fixed on `fix/model-path-observability`. If you are on an older commit, the
`providers` ↔ `retrieval` import cycle only resolves when `evidensia.retrieval`
is imported first, so a script that imports `providers` first fails:

```python
import evidensia.retrieval  # workaround: import this first
import evidensia.providers
```

## `ModuleNotFoundError: No module named 'evidensia'` in a working venv

Specific to macOS. An editable install writes a `.pth` file into
`site-packages`; if that file carries the macOS `UF_HIDDEN` flag, CPython 3.13
and later **silently skip it** (`site.py` refuses hidden `.pth` files), so the
package never reaches `sys.path`.

```bash
ls -lO .venv/lib/python3.13/site-packages/*.pth   # look for "hidden"
chflags -R nohidden .venv                          # clear it
```

Some installers re-apply the flag on every dependency change, so this can
return. Two durable alternatives: run with `PYTHONPATH=src`, or install the
project as a real (non-editable) package.

## Uploads report success but nothing is indexed

Check the API's response rather than the row in the library table. A `422`
means the parser extracted no text — most often a scanned PDF, which has no
text layer. There is no OCR step; such a document indexes as effectively empty.

```bash
curl -i -X POST http://127.0.0.1:8002/v1/documents -F "file=@paper.pdf"
```

## Discovery works, but importing a paper returns it under `missing`

Import resolves paper ids from an **in-memory** discovery cache. Restarting the
API between discovering and importing loses it. Re-run the discovery query in
the same process, then import.

## Semantic questions retrieve poorly

Expected with the default `hashed-384` embeddings. They capture exact-token
overlap and carry no semantic knowledge, so a question phrased in different
words from the source scores near zero on the dense arm.

Confirm which provider is active:

```bash
curl -s http://127.0.0.1:8002/v1/providers | python3 -m json.tool
```

Configure `EVIDENSIA_EMBEDDING_URL` for a hosted embedding provider, or phrase
queries closer to the source text. See [Evaluation](EVALUATION.md).

## Port already in use

```bash
lsof -nP -iTCP:8002 -sTCP:LISTEN     # find the holder
pkill -f "uvicorn evidensia.api"     # stop a previous instance
```

## `--reload` restarts constantly

Scope the watcher to source. Without `--reload-dir src`, uvicorn watches the
whole project including `.venv`, so any dependency change triggers a reload —
and each reload re-loads the corpus.

```bash
uvicorn evidensia.api:app --reload --reload-dir src --env-file .env --port 8002
```

## Live tests are billing my provider account

`tests/live/` makes real API calls and is skipped unless `EVIDENSIA_LIVE_TESTS=1`.
If CI is being charged, that variable is set in the CI environment. Ordinary
runs should never set it:

```bash
pytest                                  # hermetic, free
EVIDENSIA_LIVE_TESTS=1 pytest tests/live  # real calls, costs money
```
