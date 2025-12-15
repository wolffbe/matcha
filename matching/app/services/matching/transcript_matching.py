# app/services/matching/transcript_matching.py
import uuid
import logging
import hashlib
import re
from typing import Dict, List, Set
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue
import numpy as np

from app.services.matching.matching_base import (
    TRANSCRIPT_COLLECTION,
    HASH_DIM,
    euclidean_to_hamming,
    build_project_filter,
    get_project_value
)

logger = logging.getLogger(__name__)

# Character n-gram size (3 chars = more overlap, more forgiving)
CHAR_NGRAM_SIZE = 3


class TranscriptMatcher:
    def __init__(self, qdrant: QdrantClient):
        self.qdrant = qdrant

    def _normalize(self, text: str) -> str:
        """Normalize text: lowercase, remove punctuation, collapse whitespace."""
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _get_char_ngrams(self, text: str) -> Set[str]:
        """Get character n-grams from text."""
        text = self._normalize(text)
        if len(text) < CHAR_NGRAM_SIZE:
            return {text} if text else set()
        return {text[i:i+CHAR_NGRAM_SIZE] for i in range(len(text) - CHAR_NGRAM_SIZE + 1)}

    def _simhash(self, text: str) -> List[float]:
        """
        Create single SimHash signature from all character n-grams.
        
        SimHash property: P(bit_i matches) ≈ Jaccard(ngrams_A, ngrams_B)
        So hamming distance correlates with n-gram set similarity.
        """
        ngrams = self._get_char_ngrams(text)
        if not ngrams:
            return [0.0] * HASH_DIM
        
        # Accumulator for weighted bit voting
        v = np.zeros(HASH_DIM, dtype=np.int32)
        
        for ngram in ngrams:
            # Get SHA256 bits for this n-gram
            hash_bytes = hashlib.sha256(ngram.encode()).digest()
            bits = np.unpackbits(np.frombuffer(hash_bytes, dtype=np.uint8))
            # Vote: +1 for 1-bits, -1 for 0-bits
            v += np.where(bits == 1, 1, -1)
        
        # Final signature: 1 if positive votes, 0 otherwise
        return np.where(v > 0, 1.0, 0.0).tolist()

    def add_transcript(self, item_id: str, text: str, project: str = None) -> int:
        """Index transcript as single SimHash vector."""
        if not text or not text.strip():
            return 0
        
        project_value = get_project_value(project)
        
        ngrams = self._get_char_ngrams(text)
        ngram_count = len(ngrams)
        
        logger.info(f"INDEX TRANSCRIPT [{item_id[:8]}]: {text[:200]}...")
        logger.info(f"  Char {CHAR_NGRAM_SIZE}-grams: {ngram_count}")
        
        if ngram_count == 0:
            return 0
        
        vector = self._simhash(text)
        
        self.qdrant.upsert(
            collection_name=TRANSCRIPT_COLLECTION,
            points=[PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload={
                    "item_id": item_id,
                    "ngram_count": ngram_count,
                    "char_count": len(self._normalize(text)),
                    "project": project_value
                }
            )]
        )
        
        return 1

    def match_transcript(self, text: str, threshold: float, offset: float, 
                         project: str = None) -> Dict[str, float]:
        """
        Match transcript using SimHash similarity with coverage penalty.
        
        Hamming distance between SimHash signatures approximates
        (1 - Jaccard similarity) of the underlying n-gram sets.
        
        Score = hamming_similarity * coverage
        where coverage = min(query_ngrams, indexed_ngrams) / max(...)
        
        This ensures trimmed content can't score 100% against the original.
        
        threshold and offset control the hamming cutoff:
        - effective_threshold = threshold - offset
        - max_hamming = 256 * (1 - effective_threshold)
        - e.g., threshold=0.80, offset=0.05 → 75% similarity → max 64 bits different
        """
        if not text or not text.strip():
            return {}
        
        ngrams = self._get_char_ngrams(text)
        query_ngram_count = len(ngrams)
        
        logger.info(f"QUERY TRANSCRIPT: {text[:200]}...")
        logger.info(f"  Query {CHAR_NGRAM_SIZE}-grams: {query_ngram_count}")
        
        if query_ngram_count == 0:
            return {}
        
        vector = self._simhash(text)
        
        # Derive hamming thresholds from API params
        # exact_hamming: threshold alone (for rounding to 100%)
        # max_hamming: threshold - offset (for filtering results)
        # e.g., threshold=0.85, offset=0.05:
        #   exact_hamming = 256 * (1 - 0.85) = 38 bits
        #   max_hamming = 256 * (1 - 0.80) = 51 bits
        # Special case: threshold=0 means return raw scores (no rounding)
        if threshold > 0:
            exact_hamming = int(HASH_DIM * (1 - threshold))
        else:
            exact_hamming = -1  # never round to 100%
        
        effective_threshold = threshold - offset
        max_hamming = int(HASH_DIM * (1 - effective_threshold))
        
        # Ensure max_hamming >= exact_hamming so matches that round to 100% aren't filtered out
        if exact_hamming >= 0:
            max_hamming = max(max_hamming, exact_hamming)
        
        logger.info(f"  Threshold: {threshold}, offset: {offset} → exact_hamming: {exact_hamming}, max_hamming: {max_hamming}")
        
        # Build project filter
        query_filter = build_project_filter(project)
        
        # Single search - get top candidates
        search_results = self.qdrant.query_points(
            collection_name=TRANSCRIPT_COLLECTION,
            query=vector,
            query_filter=query_filter,
            limit=100
        )
        
        results = {}
        
        for pt in search_results.points:
            hamming = euclidean_to_hamming(pt.score)
            item_id = pt.payload.get("item_id")
            indexed_ngram_count = pt.payload.get("ngram_count", 1)
            
            # Coverage: ratio of smaller to larger ngram count
            # Trimmed content can't match 100% of original
            coverage = min(query_ngram_count, indexed_ngram_count) / max(query_ngram_count, indexed_ngram_count)
            
            # Score = hamming similarity * coverage
            if hamming <= exact_hamming:
                # Within exact threshold: use coverage as max
                pct = 100.0 * coverage
            else:
                # SimHash similarity scaled by coverage
                pct = (HASH_DIM - hamming) / HASH_DIM * 100 * coverage
            
            logger.info(f"  [{item_id[:8]}]: hamming={hamming}, "
                       f"ngrams=({query_ngram_count}/{indexed_ngram_count}), coverage={coverage:.1%}, score={pct:.1f}%")
            
            # Always return score, let caller decide threshold filtering
            results[item_id] = pct
        
        return results

    def delete_item(self, item_id: str, project: str = None):
        """Delete transcript for an item."""
        project_value = get_project_value(project)
        conditions = [
            FieldCondition(key="item_id", match=MatchValue(value=item_id)),
            FieldCondition(key="project", match=MatchValue(value=project_value))
        ]
        
        self.qdrant.delete(
            collection_name=TRANSCRIPT_COLLECTION,
            points_selector=Filter(must=conditions)
        )

    def get_transcript_count(self) -> int:
        """Get total number of transcripts indexed."""
        try:
            return self.qdrant.get_collection(TRANSCRIPT_COLLECTION).points_count
        except:
            return 0