"""Content addressing: the same content is the same key, and nothing else is."""

from __future__ import annotations

from filmkit import hashing


def test_the_same_payload_is_the_same_key():
    assert hashing.stable_key({"a": 1}) == hashing.stable_key({"a": 1})


def test_key_does_not_depend_on_the_order_the_dict_was_built_in():
    assert hashing.stable_key({"a": 1, "b": 2}) == hashing.stable_key({"b": 2, "a": 1})


def test_a_changed_value_is_a_changed_key():
    assert hashing.stable_key({"a": 1}) != hashing.stable_key({"a": 2})


def test_a_path_in_a_payload_does_not_crash_the_key():
    """`default=str` is what stops a cache key from becoming a TypeError."""
    from pathlib import Path

    assert hashing.stable_key({"p": Path("/x/y")}) == hashing.stable_key({"p": Path("/x/y")})


def test_file_hash_matches_the_bytes(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"hello")
    assert hashing.sha256_file(path) == hashing.sha256_bytes(b"hello")
    assert hashing.sha256_text("hello") == hashing.sha256_bytes(b"hello")


def test_a_file_larger_than_one_chunk_hashes_the_whole_thing(tmp_path):
    """The chunked read must not stop at the first megabyte."""
    path = tmp_path / "big.bin"
    payload = b"x" * ((1 << 20) + 7)
    path.write_bytes(payload)
    assert hashing.sha256_file(path) == hashing.sha256_bytes(payload)
