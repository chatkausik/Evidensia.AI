from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from evidensia.ingestion.parser import ParsedDocument, ParsedSection
from evidensia.models import ChunkRecord, DocumentMetadata


@dataclass(slots=True)
class ChunkingConfig:
    parent_words: int = 900
    retrieval_words: int = 360
    overlap_words: int = 45


class HierarchicalChunker:
    """Create parent context and retrieval chunks without crossing sections."""

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    def chunk(self, parsed: ParsedDocument, metadata: DocumentMetadata) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        global_index = 0
        for section_index, section in enumerate(parsed.sections):
            parent_texts = self._group_paragraphs(section, self.config.parent_words)
            for parent_index, parent_text in enumerate(parent_texts):
                parent_id = self._id(metadata.document_id, "parent", section_index, parent_index, parent_text)
                chunks.append(
                    self._record(
                        parent_id,
                        metadata,
                        parsed,
                        section,
                        "parent",
                        parent_text,
                        global_index,
                    )
                )
                global_index += 1
                retrieval_texts = self._sliding_chunks(parent_text, self.config.retrieval_words, self.config.overlap_words)
                for retrieval_index, retrieval_text in enumerate(retrieval_texts):
                    chunk_id = self._id(metadata.document_id, "retrieval", section_index, parent_index, retrieval_index, retrieval_text)
                    chunks.append(
                        self._record(
                            chunk_id,
                            metadata,
                            parsed,
                            section,
                            "retrieval",
                            retrieval_text,
                            global_index,
                            parent_id,
                        )
                    )
                    global_index += 1
        return chunks

    def _record(
        self,
        chunk_id: str,
        metadata: DocumentMetadata,
        parsed: ParsedDocument,
        section: ParsedSection,
        chunk_type: str,
        text: str,
        chunk_index: int,
        parent_id: str | None = None,
    ) -> ChunkRecord:
        words = re.findall(r"\S+", text)
        return ChunkRecord(
            chunk_id=chunk_id,
            document_id=metadata.document_id,
            parent_chunk_id=parent_id,
            title=metadata.title,
            section=section.heading,
            chunk_type=chunk_type,
            publication_year=metadata.publication_year,
            authors=metadata.authors,
            topics=metadata.topics,
            datasets=metadata.datasets,
            methods=metadata.methods,
            text=text.strip(),
            token_count=max(1, round(len(words) * 1.3)),
            source_uri=parsed.source_uri,
            page_number=section.page_number,
            chunk_index=chunk_index,
        )

    def _group_paragraphs(self, section: ParsedSection, limit: int) -> list[str]:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section.text) if part.strip()]
        if not paragraphs:
            return []
        output: list[str] = []
        current: list[str] = []
        count = 0
        for paragraph in paragraphs:
            words = paragraph.split()
            if len(words) > limit:
                if current:
                    output.append("\n\n".join(current))
                    current, count = [], 0
                output.extend(self._sliding_chunks(paragraph, limit, 0))
                continue
            if current and count + len(words) > limit:
                output.append("\n\n".join(current))
                current, count = [], 0
            current.append(paragraph)
            count += len(words)
        if current:
            output.append("\n\n".join(current))
        return output

    @staticmethod
    def _sliding_chunks(text: str, limit: int, overlap: int) -> list[str]:
        words = text.split()
        if len(words) <= limit:
            return [text.strip()]
        chunks: list[str] = []
        start = 0
        while start < len(words):
            stop = min(start + limit, len(words))
            # Prefer ending near a sentence boundary without breaking tables or bullets.
            if stop < len(words):
                floor = max(start + limit // 2, stop - 45)
                for index in range(stop - 1, floor - 1, -1):
                    if words[index].endswith((".", "?", "!")):
                        stop = index + 1
                        break
            chunks.append(" ".join(words[start:stop]))
            if stop >= len(words):
                break
            start = max(stop - overlap, start + 1)
        return chunks

    @staticmethod
    def _id(document_id: str, *parts: object) -> str:
        payload = "|".join([document_id, *(str(part) for part in parts)])
        return "chk_" + hashlib.sha256(payload.encode()).hexdigest()[:20]
