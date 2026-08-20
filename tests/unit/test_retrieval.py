from evidensia.models import ChunkRecord
from evidensia.retrieval import HybridSearcher, LocalKnowledgeIndex
from evidensia.retrieval.fusion import reciprocal_rank_fusion


def chunk(chunk_id: str, text: str, section: str = "Results") -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        document_id=f"doc_{chunk_id}",
        title="Retrieval Study",
        section=section,
        chunk_type="retrieval",
        text=text,
        token_count=len(text.split()),
        chunk_index=0,
    )


def test_rrf_rewards_results_present_in_both_rankings() -> None:
    a, b, c = chunk("a", "alpha"), chunk("b", "beta"), chunk("c", "gamma")
    fused = reciprocal_rank_fusion([[(a, 1.0), (b, 0.8)], [(b, 2.0), (c, 1.0)]])
    assert fused[0][0].chunk_id == "b"
    assert fused[0][2] == [2, 1]


def test_hybrid_search_surfaces_exact_and_semantic_matches() -> None:
    index = LocalKnowledgeIndex()
    index.upsert(
        [
            chunk("exact", "HotpotQA achieved Recall@10 of 89.1 with agentic RAG."),
            chunk("semantic", "Iterative retrieval improved multi-step question answering."),
            chunk("noise", "A recipe for sourdough bread uses flour and water."),
        ]
    )
    result = HybridSearcher(index).search("agentic retrieval HotpotQA Recall@10", limit=2)
    assert result.reranked[0].chunk.chunk_id == "exact"
    assert result.reranked[0].dense_rank is not None
    assert result.reranked[0].sparse_rank is not None

