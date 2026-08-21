# Evaluation

Retrieval quality is measured against gold cases through
`src/evidensia/evals/`. This document covers what each metric means, how to run
an ablation, and — most importantly — how to build a gold set that can actually
tell your pipelines apart.

## Running an evaluation

```bash
curl -s -X POST http://127.0.0.1:8002/v1/evals/run \
  -H 'Content-Type: application/json' \
  -d '{
        "cases": [
          {"id": "case_1",
           "question": "What Recall@10 did the agentic system reach on HotpotQA?",
           "gold_documents": ["doc_ff1dd7b0ef854c75"],
           "gold_chunks": [],
           "required_claims": ["Agentic retrieval reached 89.1 Recall@10"]}
        ],
        "k": 10,
        "run_ablation": true
      }'
```

`run_ablation: true` scores the same cases through all four pipelines and
returns four results. `GET /v1/evals/gold` returns the bundled cases;
`GET /v1/evals/experiments` returns stored history.

## The four pipelines

| Name | What it measures |
|---|---|
| `dense` | Embedding similarity alone (`index.dense_search`) |
| `sparse` | BM25 alone (`index.sparse_search`) |
| `hybrid` | Reciprocal-rank fusion of both, before reranking |
| `reranked` | The full pipeline, fusion plus reranking |

Reading them together is the point: `sparse` is unaffected by the embedding
provider, so it acts as a control. If `dense` moves between two runs and
`sparse` does not, the change is attributable to the embeddings rather than to
corpus drift or noise.

## Metrics

Ground truth is the union of `gold_chunks` and every chunk belonging to a
`gold_documents` entry, so a case can be labelled at either granularity. Chunk
ids are precise but break when chunking changes; document ids survive
re-chunking and are usually the better choice.

| Metric | Definition |
|---|---|
| `recall_at_k` | Fraction of relevant chunks retrieved in the top *k*. |
| `precision_at_k` | Fraction of the top *k* that are relevant. |
| `mrr` | Mean reciprocal rank of the first relevant chunk. |
| `ndcg_at_k` | Rank-discounted gain with binary relevance. |
| `hit_rate` | Fraction of cases with at least one relevant chunk in the top *k*. |
| `document_recall_at_k` | Same as recall, collapsed to documents — tolerant of chunking changes. |
| `answer_coverage` | Token overlap between `gold_answer` and retrieved text. |
| `claim_coverage` | Mean coverage across `required_claims`. |

`answer_coverage` and `claim_coverage` are lexical overlap, not semantic
judgement. They detect whether the answer's vocabulary was retrieved at all;
they cannot tell a supporting passage from a contradicting one that discusses
the same subject.

Each result carries `metadata.labeled_cases` — how many cases actually had
ground truth. **Read it before reading the metrics.** A case with neither
`gold_chunks` nor `gold_documents` contributes a zero, which drags the average
down in a way indistinguishable from genuinely poor retrieval.

## Designing a gold set that discriminates

The most common way to waste an evaluation is to build cases that every
pipeline answers perfectly. The results look excellent and carry no
information.

**Query phrasing determines what you measure.** A gold set that quotes source
text verbatim — the obvious way to generate cases automatically — measures
*lexical* matching. BM25 and hashing-trick vectors excel at exactly that, so
they score near-ceiling and a semantic embedding has nothing to contribute.
Conclusions drawn from such a set do not transfer to real research questions,
which are almost never phrased in the source's own words.

Two practical consequences:

1. **Vary the phrasing deliberately.** Include cases whose wording avoids the
   source's vocabulary while preserving its meaning. This is the condition
   under which a semantic embedding earns its cost, and the only condition
   under which you can measure that.

2. **Tighten *k* until the arms separate.** On a small corpus, Recall@10 with
   one relevant document is close to a formality. Recall@1 forces a ranking
   decision. If all four pipelines report the same number, lower *k* before
   concluding they are equivalent.

A useful sanity check: if `dense`, `sparse`, `hybrid`, and `reranked` all
return identical metrics, the gold set is not discriminating and no conclusion
about retrieval quality follows from it.

> Measured on a 103-document corpus, the gap between verbatim and paraphrased
> queries was large enough to reverse the conclusion — verbatim queries favoured
> the lexical arms, while paraphrased queries strongly favoured hosted
> embeddings. Reporting only one of the two would have argued the opposite case.
> Those measurements were taken on a variant provider configuration and are not
> reproducible from this branch; treat the methodology as the transferable part.

## Interpreting a degraded run

Retrieval metrics say nothing about whether the reasoning model ran. A run
whose model calls all failed still produces a report, still has retrieval
metrics, and still names its configured model in `provider_manifest`.

Check `GET /v1/research/{run_id}/diagnostics` and confirm `served_by` is
`model` before attributing report quality to the model. See
[API reference](API.md#run-diagnostics).
