# app/services/matching/matching_base.py
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance,
    Filter, FieldCondition, MatchValue,
    HnswConfigDiff
)
from app.config import settings

VIDEO_COLLECTION = "video_hashes"
AUDIO_COLLECTION = "audio_hashes"
IMAGE_COLLECTION = "image_hashes"
TRANSCRIPT_COLLECTION = "transcript_vectors"
HASH_DIM = 256

# Sentinel value for default project (when no project specified)
DEFAULT_PROJECT = "__default__"


def get_project_value(project: str | None) -> str:
    """Convert project parameter to storage value. None becomes DEFAULT_PROJECT."""
    return project if project is not None else DEFAULT_PROJECT


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def init_collections(qdrant: QdrantClient):
    existing = {c.name for c in qdrant.get_collections().collections}
    
    # All collections use binary vectors with Euclidean distance (for Hamming)
    for name in [VIDEO_COLLECTION, AUDIO_COLLECTION, IMAGE_COLLECTION, TRANSCRIPT_COLLECTION]:
        if name not in existing:
            qdrant.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=HASH_DIM, distance=Distance.EUCLID),
                hnsw_config=HnswConfigDiff(m=16, ef_construct=100)
            )


def hash_to_vector(hash_hex: str) -> list[float]:
    """Convert a 64-char hex hash to a 256-dim binary vector."""
    hash_bytes = bytes.fromhex(hash_hex)
    return np.unpackbits(np.frombuffer(hash_bytes, dtype=np.uint8)).astype(np.float32).tolist()


def fingerprint_to_vector(fingerprint: list[int]) -> list[float]:
    """Convert audio fingerprint integers to a 256-dim binary vector."""
    FINGERPRINT_INTS = 8
    fp = (fingerprint[:FINGERPRINT_INTS] + [0] * FINGERPRINT_INTS)[:FINGERPRINT_INTS]
    result = []
    for val in fp:
        v = int(val) & 0xFFFFFFFF
        result.extend([
            (v >> 24) & 0xFF,
            (v >> 16) & 0xFF,
            (v >> 8) & 0xFF,
            v & 0xFF
        ])
    binary = bytes(result)
    return np.unpackbits(np.frombuffer(binary, dtype=np.uint8)).astype(np.float32).tolist()


def euclidean_to_hamming(euclidean_dist: float) -> int:
    """Convert Euclidean distance to Hamming distance for binary vectors."""
    return int(round(euclidean_dist ** 2))


def build_project_filter(project: str | None, additional_conditions: list = None) -> Filter:
    """Build a Qdrant filter for project-based queries.
    
    Args:
        project: Project name to filter by. None = filter for default project
        additional_conditions: Additional filter conditions to include
        
    Returns:
        Filter object
    """
    conditions = list(additional_conditions) if additional_conditions else []
    
    # Convert None to default project sentinel value
    project_value = get_project_value(project)
    conditions.append(FieldCondition(key="project", match=MatchValue(value=project_value)))
    
    return Filter(must=conditions)


def build_item_filter(item_id: str, project: str | None = None) -> Filter:
    """Build a filter for item_id with project constraint."""
    project_value = get_project_value(project)
    conditions = [
        FieldCondition(key="item_id", match=MatchValue(value=item_id)),
        FieldCondition(key="project", match=MatchValue(value=project_value))
    ]
    
    return Filter(must=conditions)


def count_segments(qdrant: QdrantClient, collection: str, item_id: str, project: str | None = None) -> int:
    """Count segments for an item in a collection, filtered by project."""
    result = qdrant.count(
        collection_name=collection,
        count_filter=build_item_filter(item_id, project),
        exact=True
    )
    return result.count


def count_collection(qdrant: QdrantClient, collection: str, project: str | None = None) -> int:
    """Count total items in a collection, filtered by project."""
    result = qdrant.count(
        collection_name=collection,
        count_filter=build_project_filter(project),
        exact=True
    )
    return result.count