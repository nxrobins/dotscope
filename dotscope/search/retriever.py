"""Compiled Retrieval: hybrid dense + BM25 search with RRF fusion.

Storage layout in .dotscope/cache/:
  vectors.npy          — float32 [n_chunks x dimensions], raw binary (mmap'd)
  vectors_meta.json    — List[RetrievalChunk] metadata (sans embedding)
  bm25_index.json      — Inverted index for BM25 scoring
  vector_index.json    — VectorIndex metadata (model, dimensions, freshness)

Zero-dependency default: BM25-only retrieval using the inverted index.
Optional sentence-transformers enables dense cosine + RRF fusion.
"""

import json
import math
import os
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import RetrievalChunk, SearchResult, VectorIndex

# BM25 parameters
BM25_K1 = 1.2
BM25_B = 0.75

# RRF fusion constant
RRF_K = 60

# Staleness threshold (commits since last vector update)
STALE_COMMIT_THRESHOLD = 50


# ---------------------------------------------------------------------------
# Index Building
# ---------------------------------------------------------------------------

def build_vector_index(
    root: str,
    chunks: List[RetrievalChunk],
    model_name: str = "all-MiniLM-L6-v2",
) -> VectorIndex:
    """Build or rebuild the embedding index during dotscope ingest.

    Builds BM25 inverted index (always). Builds dense embeddings
    (only if sentence-transformers is available).
    """
    cache_dir = Path(root) / ".dotscope" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Build BM25 index (always)
    bm25 = build_bm25_index(chunks)
    with open(cache_dir / "bm25_index.json", "w", encoding="utf-8") as f:
        json.dump(bm25, f)

    # Save chunk metadata
    meta = [asdict(c) for c in chunks]
    with open(cache_dir / "vectors_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f)

    # Try dense embeddings
    dimensions = 0
    try:
        embeddings = _embed_texts([c.content for c in chunks])
        if embeddings is not None:
            import numpy as np
            np.save(str(cache_dir / "vectors.npy"), embeddings)
            dimensions = embeddings.shape[1]
            model_name = model_name
    except Exception:
        pass  # No sentence-transformers — BM25 only

    # Get current HEAD commit
    head_commit = _git_head(root)

    index = VectorIndex(
        model_name=model_name if dimensions > 0 else "bm25-only",
        dimensions=dimensions,
        file_count=len(set(c.file_path for c in chunks)),
        chunk_count=len(chunks),
        built_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        last_vector_update_commit=head_commit,
    )

    with open(cache_dir / "vector_index.json", "w", encoding="utf-8") as f:
        json.dump(asdict(index), f, indent=2)

    return index


def build_bm25_index(chunks: List[RetrievalChunk]) -> dict:
    """Build an inverted index for BM25 scoring.

    Structure:
    {
      "_N": 500000, "_avg_dl": 142.3, "_doc_lengths": [120, ...],
      "stripe": [{"chunk_id": 4821, "tf": 3}, ...],
    }
    """
    index: Dict[str, list] = {"_N": len(chunks), "_doc_lengths": []}
    term_postings: Dict[str, list] = {}
    total_tokens = 0

    for chunk in chunks:
        tokens = _tokenize(chunk.content)
        doc_len = len(tokens)
        index["_doc_lengths"].append(doc_len)
        total_tokens += doc_len

        # Count term frequencies
        tf: Dict[str, int] = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1

        for term, count in tf.items():
            if term not in term_postings:
                term_postings[term] = []
            term_postings[term].append({"chunk_id": chunk.chunk_id, "tf": count})

    index["_avg_dl"] = total_tokens / len(chunks) if chunks else 0
    index.update(term_postings)
    return index


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(query: str, root: str, limit: int = 10) -> List[SearchResult]:
    """Hybrid retrieval: dense cosine + BM25 keyword, RRF-fused."""
    cache_dir = Path(root) / ".dotscope" / "cache"

    # Load metadata
    metadata = _load_metadata(cache_dir)
    if not metadata:
        return []

    # BM25 path (always available)
    bm25_index = _load_bm25_index(cache_dir)
    bm25_results = _bm25_search(query, bm25_index, limit=50) if bm25_index else []

    # Dense path (if embeddings available)
    dense_results = []
    embeddings = _load_embeddings(cache_dir)
    if embeddings is not None:
        dense_results = _dense_search(query, embeddings, limit=50)

    # Fusion
    if dense_results and bm25_results:
        fused = _rrf_fusion(dense_results, bm25_results, limit=limit)
    elif bm25_results:
        fused = [(cid, 0.0, score, score) for cid, score in bm25_results[:limit]]
    elif dense_results:
        fused = [(cid, score, 0.0, score) for cid, score in dense_results[:limit]]
    else:
        return []

    # Build SearchResult objects
    results = []
    for chunk_id, dense_score, bm25_score, rrf_score in fused:
        if chunk_id < len(metadata):
            chunk = metadata[chunk_id]
            results.append(SearchResult(
                file_path=chunk.file_path,
                chunk=chunk,
                dense_score=dense_score,
                bm25_score=bm25_score,
                rrf_score=rrf_score,
                recency_adjusted=rrf_score,
            ))

    return results


def check_index_freshness(root: str) -> Tuple[bool, str]:
    """Returns (is_fresh, reason)."""
    cache_dir = Path(root) / ".dotscope" / "cache"
    index_path = cache_dir / "vector_index.json"

    if not index_path.exists():
        return False, "No index found. Run dotscope ingest."

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        last_commit = data.get("last_vector_update_commit", "")
    except Exception:
        return False, "Cannot read index metadata."

    if not last_commit:
        return False, "Index has no commit watermark."

    # Count commits since last update
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{last_commit}..HEAD"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            gap = int(result.stdout.strip())
            if gap > STALE_COMMIT_THRESHOLD:
                return False, f"Index is {gap} commits behind HEAD."
            return True, f"Fresh ({gap} commits since last update)."
    except Exception:
        pass

    return False, "Cannot determine index freshness."


# ---------------------------------------------------------------------------
# BM25 Implementation
# ---------------------------------------------------------------------------

def _bm25_search(query: str, index: dict, limit: int = 50) -> List[Tuple[int, float]]:
    """Score only chunks containing query terms. Returns [(chunk_id, score)]."""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    N = index.get("_N", 0)
    avg_dl = index.get("_avg_dl", 1)
    doc_lengths = index.get("_doc_lengths", [])

    # Collect candidate chunk IDs from postings lists
    candidates: Dict[int, float] = {}

    for term in query_tokens:
        postings = index.get(term, [])
        if not postings:
            continue

        df = len(postings)
        idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)

        for posting in postings:
            chunk_id = posting["chunk_id"]
            tf = posting["tf"]
            dl = doc_lengths[chunk_id] if chunk_id < len(doc_lengths) else avg_dl

            numerator = tf * (BM25_K1 + 1)
            denominator = tf + BM25_K1 * (1 - BM25_B + BM25_B * dl / avg_dl)
            score = idf * numerator / denominator

            candidates[chunk_id] = candidates.get(chunk_id, 0.0) + score

    ranked = sorted(candidates.items(), key=lambda x: -x[1])
    return ranked[:limit]


# ---------------------------------------------------------------------------
# Dense Retrieval
# ---------------------------------------------------------------------------

def _load_embeddings(cache_dir: Path):
    """Memory-map the embedding matrix. Returns None if unavailable."""
    path = cache_dir / "vectors.npy"
    if not path.exists():
        return None
    try:
        import numpy as np
        return np.load(str(path), mmap_mode="r")
    except Exception:
        return None


def _dense_search(query: str, embeddings, limit: int = 50) -> List[Tuple[int, float]]:
    """Cosine similarity search against mmap'd embedding matrix."""
    try:
        import numpy as np
        query_vec = _embed_texts([query])
        if query_vec is None:
            return []
        # Cosine similarity: query_vec @ embeddings.T
        query_vec = query_vec[0]
        # Normalize
        query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-10
        similarities = embeddings @ query_norm / norms.squeeze()
        top_ids = np.argsort(similarities)[::-1][:limit]
        return [(int(idx), float(similarities[idx])) for idx in top_ids]
    except Exception:
        return []


def _embed_texts(texts: List[str], batch_size: int = 512):
    """Embed texts in batches using sentence-transformers. Returns numpy array or None."""
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np

        model = SentenceTransformer("all-MiniLM-L6-v2")

        if len(texts) <= batch_size:
            return model.encode(texts, show_progress_bar=False, convert_to_numpy=True)

        # Batch to avoid OOM on large repos
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                embeddings = model.encode(batch, show_progress_bar=False, convert_to_numpy=True)
                all_embeddings.append(embeddings)
            except Exception:
                continue  # Skip failed batch, keep going

        if not all_embeddings:
            return None
        return np.vstack(all_embeddings)
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# RRF Fusion
# ---------------------------------------------------------------------------

def _rrf_fusion(
    dense_results: List[Tuple[int, float]],
    bm25_results: List[Tuple[int, float]],
    limit: int = 10,
) -> List[Tuple[int, float, float, float]]:
    """Reciprocal Rank Fusion. Returns [(chunk_id, dense_score, bm25_score, rrf_score)]."""
    dense_ranks = {cid: rank + 1 for rank, (cid, _) in enumerate(dense_results)}
    bm25_ranks = {cid: rank + 1 for rank, (cid, _) in enumerate(bm25_results)}
    dense_scores = {cid: score for cid, score in dense_results}
    bm25_scores = {cid: score for cid, score in bm25_results}

    all_ids = set(dense_ranks.keys()) | set(bm25_ranks.keys())
    fused = []

    for cid in all_ids:
        d_rank = dense_ranks.get(cid, len(dense_results) + 100)
        b_rank = bm25_ranks.get(cid, len(bm25_results) + 100)
        rrf = 1.0 / (RRF_K + d_rank) + 1.0 / (RRF_K + b_rank)
        fused.append((cid, dense_scores.get(cid, 0.0), bm25_scores.get(cid, 0.0), rrf))

    fused.sort(key=lambda x: -x[3])
    return fused[:limit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_metadata(cache_dir: Path) -> List[RetrievalChunk]:
    """Load chunk metadata from sidecar."""
    path = cache_dir / "vectors_meta.json"
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [RetrievalChunk(**item) for item in data]
    except Exception:
        return []


def _load_bm25_index(cache_dir: Path) -> Optional[dict]:
    path = cache_dir / "bm25_index.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _tokenize(text: str) -> List[str]:
    """Simple whitespace + punctuation tokenizer for BM25."""
    import re
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())
    return [t for t in tokens if len(t) > 1]


def _git_head(root: str) -> str:
    """Get current git HEAD commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""
