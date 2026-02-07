import uuid
import re
from datetime import datetime

import fitz  # PyMuPDF
import chromadb


class KnowledgeBase:
    def __init__(self, persist_dir: str = "data/chroma"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name="knowledge",
            metadata={"hnsw:space": "cosine"},
        )

    def _chunk_text(self, text: str, max_chars: int = 500) -> list[str]:
        """Split text into chunks by paragraphs, respecting max_chars."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) + 2 > max_chars and current:
                chunks.append(current.strip())
                current = para
            else:
                current = f"{current}\n\n{para}" if current else para

        if current.strip():
            chunks.append(current.strip())

        # Split any remaining oversized chunks
        final = []
        for chunk in chunks:
            if len(chunk) <= max_chars:
                final.append(chunk)
            else:
                # Split by sentences
                sentences = re.split(r'(?<=[.!?])\s+', chunk)
                buf = ""
                for s in sentences:
                    if len(buf) + len(s) + 1 > max_chars and buf:
                        final.append(buf.strip())
                        buf = s
                    else:
                        buf = f"{buf} {s}" if buf else s
                if buf.strip():
                    final.append(buf.strip())

        return [c for c in final if len(c) > 20]  # Skip tiny fragments

    def add_pdf(self, file_bytes: bytes, filename: str) -> dict:
        """Extract text from PDF and index it."""
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text() + "\n\n"
        doc.close()

        return self._index_document(full_text, filename, "pdf")

    def add_text(self, text: str, filename: str, doc_type: str) -> dict:
        """Index plain text (notes, audio transcripts)."""
        return self._index_document(text, filename, doc_type)

    def add_chat_export(self, text: str, filename: str) -> dict:
        """Parse and index WhatsApp chat export."""
        # Group messages into conversation blocks of ~5-8 messages
        lines = text.strip().split("\n")
        blocks = []
        current_block = []

        for line in lines:
            current_block.append(line)
            if len(current_block) >= 6:
                blocks.append("\n".join(current_block))
                current_block = []

        if current_block:
            blocks.append("\n".join(current_block))

        doc_id = str(uuid.uuid4())[:8]
        ids = []
        documents = []
        metadatas = []

        for i, block in enumerate(blocks):
            if len(block.strip()) < 20:
                continue
            chunk_id = f"{doc_id}_chunk_{i}"
            ids.append(chunk_id)
            documents.append(block)
            metadatas.append({
                "doc_id": doc_id,
                "source": filename,
                "type": "chat_history",
                "chunk_index": i,
            })

        if ids:
            self.collection.add(ids=ids, documents=documents, metadatas=metadatas)

        return {
            "id": doc_id,
            "filename": filename,
            "doc_type": "chat_history",
            "chunk_count": len(ids),
            "created_at": datetime.now().isoformat(),
        }

    def _index_document(self, text: str, filename: str, doc_type: str) -> dict:
        """Chunk and index a document."""
        chunks = self._chunk_text(text)
        doc_id = str(uuid.uuid4())[:8]

        ids = []
        documents = []
        metadatas = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{i}"
            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({
                "doc_id": doc_id,
                "source": filename,
                "type": doc_type,
                "chunk_index": i,
            })

        if ids:
            self.collection.add(ids=ids, documents=documents, metadatas=metadatas)

        return {
            "id": doc_id,
            "filename": filename,
            "doc_type": doc_type,
            "chunk_count": len(ids),
            "created_at": datetime.now().isoformat(),
        }

    def search(self, query: str, n_results: int = 5) -> list[str]:
        """Search for relevant chunks."""
        if self.collection.count() == 0:
            return []

        n = min(n_results, self.collection.count())
        results = self.collection.query(query_texts=[query], n_results=n)
        return results["documents"][0] if results["documents"] else []

    def list_documents(self) -> list[dict]:
        """List all unique documents in the knowledge base."""
        if self.collection.count() == 0:
            return []

        all_data = self.collection.get(include=["metadatas"])
        docs = {}
        for meta in all_data["metadatas"]:
            doc_id = meta["doc_id"]
            if doc_id not in docs:
                docs[doc_id] = {
                    "id": doc_id,
                    "filename": meta["source"],
                    "doc_type": meta["type"],
                    "chunk_count": 0,
                }
            docs[doc_id]["chunk_count"] += 1

        return list(docs.values())

    def delete_document(self, doc_id: str) -> bool:
        """Delete all chunks belonging to a document."""
        if self.collection.count() == 0:
            return False

        all_data = self.collection.get(include=["metadatas"])
        ids_to_delete = [
            id_ for id_, meta in zip(all_data["ids"], all_data["metadatas"])
            if meta.get("doc_id") == doc_id
        ]

        if ids_to_delete:
            self.collection.delete(ids=ids_to_delete)
            return True
        return False
