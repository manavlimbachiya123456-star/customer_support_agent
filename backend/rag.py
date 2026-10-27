"""RAG: read policy documents, split into chunks, embed, store in Qdrant, search.

MOCK_LLM=true uses a simple hash-based embedding (keyword matching) so everything works offline.
MOCK_LLM=false uses Gemini embeddings (gemini-embedding-001).
"""
import hashlib
import io
import os
import re
import uuid

import config
from db import db, new_id, utcnow

from qdrant_client import QdrantClient
from qdrant_client.models import (Distance, FieldCondition, Filter, FilterSelector, MatchValue,
                                  PointStruct, VectorParams)

ALLOWED_EXT = {".pdf", ".md", ".txt"}
MAX_BYTES = 5 * 1024 * 1024
DOC_TYPES = ["refund", "shipping", "cancellation", "return", "faq"]
MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.10"))

_qdrant = None
_genai = None


class KBError(Exception):
    """Safe-to-show error (bad upload etc.). `status` is the HTTP code the API uses."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- embeddings
STOP = {"the", "and", "for", "are", "was", "you", "your", "with", "that", "this", "from", "have", "has",
        "will", "can", "not", "any", "our", "but", "all", "its", "may", "who", "how", "what", "when"}


def mock_embed(text: str):
    vec = [0.0] * config.EMBED_DIM
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) < 3 or w in STOP:
            continue
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        vec[int(hashlib.md5(w.encode()).hexdigest()[:8], 16) % config.EMBED_DIM] += 1.0
    if not any(vec):
        vec[0] = 1.0
    return vec


def embed(text: str):
    if config.mock_llm():
        return mock_embed(text)
    global _genai
    from google import genai
    from google.genai import types

    if _genai is None:
        _genai = genai.Client(api_key=config.get("GEMINI_API_KEY"))
    res = _genai.models.embed_content(
        model=config.EMBED_MODEL, contents=text,
        config=types.EmbedContentConfig(output_dimensionality=config.EMBED_DIM))
    return list(res.embeddings[0].values)


def mode() -> str:
    return "mock" if config.mock_llm() else "gemini"


def collection_name() -> str:
    return f"policies_{mode()}"  # separate collections so mock and Gemini vectors never mix


# ---------------------------------------------------------------- qdrant
def qdrant() -> QdrantClient:
    global _qdrant
    if _qdrant is None:
        url = config.get("QDRANT_URL")
        if url:
            _qdrant = QdrantClient(url=url)
        else:
            _qdrant = QdrantClient(path=config.get("QDRANT_PATH", "./qdrant_data")) \
                if config.get("QDRANT_PATH", "./qdrant_data") != ":memory:" else QdrantClient(":memory:")
    return _qdrant


def ensure_collection():
    q = qdrant()
    name = collection_name()
    if not q.collection_exists(name):
        q.create_collection(name, vectors_config=VectorParams(size=config.EMBED_DIM, distance=Distance.COSINE))
    return name


def reset_collection():
    q = qdrant()
    for m in ("mock", "gemini"):
        n = f"policies_{m}"
        if q.collection_exists(n):
            q.delete_collection(n)
    ensure_collection()


def _doc_filter(doc_id=None, doc_type=None):
    must = []
    if doc_id:
        must.append(FieldCondition(key="doc_id", match=MatchValue(value=doc_id)))
    if doc_type:
        must.append(FieldCondition(key="doc_type", match=MatchValue(value=doc_type)))
    return Filter(must=must) if must else None


# ---------------------------------------------------------------- reading + chunking
def extract_pages(filename: str, data: bytes):
    """Returns a list of (page_number_or_None, text)."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise KBError("File does not look like a real PDF.")
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise KBError("Encrypted PDFs are not supported.")
            return [(i + 1, (p.extract_text() or "")) for i, p in enumerate(reader.pages)]
        except KBError:
            raise
        except Exception:
            raise KBError("Could not read this PDF.")
    try:
        return [(None, data.decode("utf-8"))]
    except UnicodeDecodeError:
        raise KBError("Text files must be UTF-8.")


def split_text(text: str, max_chars: int = 500):
    """Split on blank lines, then join small paragraphs until a chunk is about max_chars."""
    chunks, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if current and len(current) + len(para) > max_chars:
            chunks.append(current)
            current = ""
        # a heading stays together with the paragraph below it
        current = (current + "\n\n" + para).strip() if current else para
        while len(current) > max_chars * 1.5:
            chunks.append(current[:max_chars])
            current = current[max_chars:]
    if current:
        chunks.append(current)
    return chunks


def guess_doc_type(filename: str) -> str:
    name = filename.lower()
    for t, keys in (("refund", ["refund"]), ("shipping", ["shipping", "delivery"]),
                    ("cancellation", ["cancel"]), ("return", ["return"])):
        if any(k in name for k in keys):
            return t
    return "faq"


# ---------------------------------------------------------------- safety
INJECTION = re.compile(
    r"(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|system)\s+"
    r"(instructions?|rules?|prompts?|policy|policies)"
    r"|you\s+are\s+now\b|system\s+prompt|act\s+as\s+(an?\s+)?(admin|system|developer)"
    r"|(approve|issue|process)\s+(all|every|any)\s+refunds?"
    r"|without\s+(human\s+)?approval", re.I)


def sanitize(text: str):
    """Documents are data, not instructions. Remove instruction-like phrases and flag them."""
    cleaned, n = INJECTION.subn("[instruction-like text removed]", text)
    return cleaned, n > 0


# ---------------------------------------------------------------- ingestion
def _public(doc):
    return {k: v for k, v in doc.items() if k not in ("_id", "text")}


def _index(doc):
    """Chunk + embed + store one document. Updates its status."""
    name = ensure_collection()
    try:
        db.documents.update_one({"doc_id": doc["doc_id"]}, {"$set": {"status": "INDEXING", "error": None}})
        qdrant().delete(name, points_selector=FilterSelector(filter=_doc_filter(doc_id=doc["doc_id"])))
        points = []
        for page, page_text in doc["pages"]:
            for i, chunk in enumerate(split_text(page_text)):
                chunk_id = f"{doc['doc_id']}-p{page or 1}-c{i}"
                points.append(PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id)), vector=embed(chunk),
                    payload={"text": chunk, "source": doc["filename"], "doc_id": doc["doc_id"],
                             "doc_type": doc["doc_type"], "chunk_id": chunk_id, "page": page,
                             "uploaded_at": doc["uploaded_at"].isoformat()}))
        if not points:
            raise KBError("No readable text found in this document.")
        qdrant().upsert(name, points)
        db.documents.update_one({"doc_id": doc["doc_id"]}, {"$set": {
            "status": "INDEXED", "chunks": len(points), "index_mode": mode(), "indexed_at": utcnow()}})
    except KBError as e:
        db.documents.update_one({"doc_id": doc["doc_id"]}, {"$set": {"status": "FAILED", "error": str(e)}})
        raise
    except Exception:
        db.documents.update_one({"doc_id": doc["doc_id"]},
                                {"$set": {"status": "FAILED", "error": "Indexing failed (see server logs)."}})
        raise


def ingest(filename: str, data: bytes, doc_type: str = "", replace: bool = False, uploaded_by: str = "system"):
    filename = os.path.basename(filename or "")
    if not re.fullmatch(r"[\w\-. ]{1,100}", filename):
        raise KBError("Invalid file name.")
    if os.path.splitext(filename)[1].lower() not in ALLOWED_EXT:
        raise KBError("Only .pdf, .md and .txt files are supported.")
    if not data:
        raise KBError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise KBError("File is larger than 5 MB.", 413)
    if doc_type and doc_type not in DOC_TYPES:
        raise KBError(f"doc_type must be one of {DOC_TYPES}.")

    pages = extract_pages(filename, data)  # validates the content
    if not any(t.strip() for _, t in pages):
        raise KBError("No readable text found in this document.")

    content_hash = hashlib.sha256(data).hexdigest()
    same = db.documents.find_one({"content_hash": content_hash})
    if same:
        raise KBError(f"Duplicate: this exact content is already indexed as '{same['filename']}'.", 409)
    old = db.documents.find_one({"filename": filename})
    if old and not replace:
        raise KBError("A document with this name exists. Upload with replace=true to replace it.", 409)
    if old:
        delete_document(old["doc_id"])

    doc = {"doc_id": new_id("DOC"), "filename": filename, "doc_type": doc_type or guess_doc_type(filename),
           "status": "UPLOADED", "content_hash": content_hash, "size": len(data), "chunks": 0,
           "uploaded_by": uploaded_by, "uploaded_at": utcnow(), "index_mode": None, "error": None,
           "text": "\n\n".join(t for _, t in pages), "pages": [[p, t] for p, t in pages]}
    db.documents.insert_one(dict(doc))
    _index({**doc, "pages": pages})
    return _public(db.documents.find_one({"doc_id": doc["doc_id"]}))


def reindex(doc_id: str):
    doc = db.documents.find_one({"doc_id": doc_id})
    if not doc:
        raise KBError("Document not found.", 404)
    _index({**doc, "pages": [tuple(p) for p in doc["pages"]], "uploaded_at": doc["uploaded_at"]})
    return _public(db.documents.find_one({"doc_id": doc_id}))


def delete_document(doc_id: str):
    doc = db.documents.find_one({"doc_id": doc_id})
    if not doc:
        raise KBError("Document not found.", 404)
    q = qdrant()
    for m in ("mock", "gemini"):
        n = f"policies_{m}"
        if q.collection_exists(n):
            q.delete(n, points_selector=FilterSelector(filter=_doc_filter(doc_id=doc_id)))
    db.documents.delete_one({"doc_id": doc_id})


def list_documents():
    return [_public(d) for d in db.documents.find({}).sort("uploaded_at", -1)]


def sync_index():
    """On startup: re-index documents whose vectors are missing or were built in another mode."""
    name = ensure_collection()
    for doc in db.documents.find({}):
        have = qdrant().count(name, count_filter=_doc_filter(doc_id=doc["doc_id"]), exact=True).count
        if doc.get("index_mode") != mode() or have == 0:
            try:
                reindex(doc["doc_id"])
            except Exception:
                pass


# ---------------------------------------------------------------- search
def search(question: str, doc_type: str = None, k: int = 3):
    """Returns passages with citations: text, source file, chunk_id, page, score."""
    name = ensure_collection()
    hits = qdrant().query_points(name, query=embed(question), limit=k,
                                 query_filter=_doc_filter(doc_type=doc_type)).points
    out = []
    for h in hits:
        text, suspicious = sanitize(h.payload["text"])
        out.append({"text": text, "source": h.payload["source"], "chunk_id": h.payload["chunk_id"],
                    "page": h.payload.get("page"), "doc_type": h.payload["doc_type"],
                    "score": round(float(h.score), 3), "suspicious": suspicious})
    return out
