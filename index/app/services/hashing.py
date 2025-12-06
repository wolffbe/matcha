import numpy as np


class HashingService:
    FINGERPRINT_INTS = 8

    @staticmethod
    def hex_to_bytes(hex_str: str) -> np.ndarray:
        return np.array([int(hex_str[i:i+2], 16) for i in range(0, 64, 2)], dtype=np.uint8)

    @classmethod
    def fingerprint_to_binary(cls, fingerprint: list[int]) -> np.ndarray:
        if len(fingerprint) >= cls.FINGERPRINT_INTS:
            fp = fingerprint[:cls.FINGERPRINT_INTS]
        else:
            fp = fingerprint + [0] * (cls.FINGERPRINT_INTS - len(fingerprint))

        return np.array([
            (int(val) >> shift) & 0xFF
            for val in fp
            for shift in [24, 16, 8, 0]
        ], dtype=np.uint8)