from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from evidensia.ingestion import DocumentParser, HierarchicalChunker, extract_metadata
from evidensia.models import ChunkRecord, DocumentMetadata, DocumentRecord, DocumentStatus
from evidensia.retrieval import LocalKnowledgeIndex


class KnowledgeService:
    """Local document service; provider boundaries allow Pinecone/object storage later."""

    def __init__(self, index: LocalKnowledgeIndex | None = None, storage_dir: str | Path | None = None) -> None:
        self.index = index or LocalKnowledgeIndex()
        self.parser = DocumentParser()
        self.chunker = HierarchicalChunker()
        self.storage_dir = Path(storage_dir).resolve() if storage_dir else None
        self.documents: dict[str, DocumentRecord] = {}
        self._raw: dict[str, tuple[str, bytes, str, str | None, dict[str, Any] | None]] = {}
        self._all_chunks: dict[str, ChunkRecord] = {}
        self._loading = False
        if self.storage_dir:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            self._load_persisted()

    def ingest(
        self,
        filename: str,
        content: bytes,
        content_type: str = "text/plain",
        source_uri: str | None = None,
        metadata_overrides: dict[str, Any] | None = None,
        document_id: str | None = None,
    ) -> DocumentRecord:
        resolved_id = document_id or f"doc_{uuid.uuid4().hex[:16]}"
        record = DocumentRecord(
            document_id=resolved_id,
            filename=filename,
            content_type=content_type,
            source_uri=source_uri,
            status=DocumentStatus.QUEUED,
        )
        self.documents[resolved_id] = record
        self._raw[resolved_id] = (filename, content, content_type, source_uri, metadata_overrides)
        try:
            parsed = self.parser.parse(filename, content, content_type, source_uri)
            metadata = extract_metadata(resolved_id, parsed)
            if metadata_overrides:
                metadata = DocumentMetadata.model_validate({**metadata.model_dump(), **metadata_overrides})
            chunks = self.chunker.chunk(parsed, metadata)
            self.index.delete_document(resolved_id)
            self.index.upsert(chunks)
            for chunk_id in [key for key, value in self._all_chunks.items() if value.document_id == resolved_id]:
                self._all_chunks.pop(chunk_id, None)
            self._all_chunks.update({chunk.chunk_id: chunk for chunk in chunks})
            record = record.model_copy(
                update={
                    "status": DocumentStatus.INDEXED,
                    "metadata": metadata,
                    "chunk_count": sum(chunk.chunk_type == "retrieval" for chunk in chunks),
                }
            )
        except Exception as exc:
            record = record.model_copy(update={"status": DocumentStatus.FAILED, "error": str(exc)})
        self.documents[resolved_id] = record
        if self.storage_dir and not self._loading and record.status == DocumentStatus.INDEXED:
            self._persist(resolved_id)
        return record

    def reindex(self, document_id: str) -> DocumentRecord | None:
        raw = self._raw.get(document_id)
        if not raw:
            return None
        return self.ingest(*raw, document_id=document_id)

    def delete(self, document_id: str) -> bool:
        if document_id not in self.documents:
            return False
        self.documents.pop(document_id, None)
        self._raw.pop(document_id, None)
        self.index.delete_document(document_id)
        for chunk_id in [key for key, value in self._all_chunks.items() if value.document_id == document_id]:
            self._all_chunks.pop(chunk_id, None)
        if self.storage_dir:
            document_dir = self.storage_dir / document_id
            if document_dir.is_dir() and document_dir.parent == self.storage_dir:
                shutil.rmtree(document_dir)
        return True

    def get_chunk(self, chunk_id: str) -> ChunkRecord | None:
        return self._all_chunks.get(chunk_id)

    def list_documents(self) -> list[DocumentRecord]:
        return sorted(self.documents.values(), key=lambda item: item.created_at, reverse=True)

    def _persist(self, document_id: str) -> None:
        raw = self._raw.get(document_id)
        if not raw or not self.storage_dir:
            return
        filename, content, content_type, source_uri, metadata_overrides = raw
        document_dir = self.storage_dir / document_id
        document_dir.mkdir(parents=True, exist_ok=True)
        (document_dir / "content.bin").write_bytes(content)
        manifest = {
            "filename": filename,
            "content_type": content_type,
            "source_uri": source_uri,
            "metadata_overrides": metadata_overrides,
        }
        (document_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def _load_persisted(self) -> None:
        if not self.storage_dir:
            return
        self._loading = True
        try:
            for document_dir in sorted(self.storage_dir.glob("doc_*")):
                manifest_path = document_dir / "manifest.json"
                content_path = document_dir / "content.bin"
                if not document_dir.is_dir() or not manifest_path.is_file() or not content_path.is_file():
                    continue
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.ingest(
                        manifest["filename"],
                        content_path.read_bytes(),
                        manifest["content_type"],
                        manifest.get("source_uri"),
                        manifest.get("metadata_overrides"),
                        document_id=document_dir.name,
                    )
                except (KeyError, OSError, ValueError, json.JSONDecodeError):
                    continue
        finally:
            self._loading = False
