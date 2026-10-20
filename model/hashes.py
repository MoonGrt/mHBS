"""Primitive accounting for the recipe interpreter and vector metadata.

A hash event is one complete SHAKE/SHA256 invocation. SHA2 permutation events
count SHA256 compression blocks, including padding; HMAC uses two hashes.
"""
import hashlib


def block_count(length, hash_backend="shake"):
    if length < 0:
        raise ValueError("negative hash input length")
    if hash_backend == "shake":
        return length // 136 + 1
    if hash_backend == "sha2":
        return (length + 9 + 63) // 64
    raise ValueError(f"unknown hash backend: {hash_backend}")


def digest(data, length, hash_backend="shake"):
    if hash_backend == "shake":
        return hashlib.shake_256(data).digest(length)
    if hash_backend == "sha2" and 0 < length <= 32:
        return hashlib.sha256(data).digest()[:length]
    raise ValueError("unsupported hash backend or digest length")
