import numpy as np

FINGERPRINT_INTS = 8


def hex_to_bytes(hex_str: str) -> bytes:
    """Convert hex hash string to bytes."""
    return bytes.fromhex(hex_str)


def fingerprint_to_binary(fingerprint: list[int]) -> bytes:
    """Convert Chromaprint fingerprint to binary bytes."""
    if len(fingerprint) >= FINGERPRINT_INTS:
        fp = fingerprint[:FINGERPRINT_INTS]
    else:
        fp = fingerprint + [0] * (FINGERPRINT_INTS - len(fingerprint))
    
    result = []
    for val in fp:
        result.extend([
            (int(val) >> 24) & 0xFF,
            (int(val) >> 16) & 0xFF,
            (int(val) >> 8) & 0xFF,
            int(val) & 0xFF
        ])
    return bytes(result)