# Copyright 2004-2026 Tom Rothamel <pytom@bishoujo.us>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

"""Packaged-file blob helpers for this Ren'Py fork.

This intentionally uses only the Python standard library so the fork does not
gain new platform packaging requirements.
"""

from __future__ import annotations

import hashlib
import zlib


ARCHIVE_EXTENSION = ".rnx"
COMPILED_SCRIPT_EXTENSION = ".rsc"
COMPILED_MODULE_EXTENSION = ".rsm"
LEGACY_ARTIFACT_EXTENSIONS = (".rpa", ".rpyc", ".rpymc")

ARCHIVE_MAGIC = b"RNX-1.0 "
ARCHIVE_HEADER = ARCHIVE_MAGIC + b"%016x %016x\n"
ARCHIVE_HEADER_PLACEHOLDER = ARCHIVE_MAGIC + b"XXXXXXXXXXXXXXXX XXXXXXXXXXXXXXXX\n"

COMPILED_SCRIPT_HEADER = b"RNX SCRIPT2"

ARCHIVE_INDEX_PURPOSE = b"archive-index"
ARCHIVE_MEMBER_PURPOSE = b"archive-member"
COMPILED_SCRIPT_PURPOSE = b"compiled-script"

# This key is embedded in the client, so this is obfuscation rather than DRM.
_KEY = b"renpy-fork-rnx-format-2026-06-17"
_BLAKE_KEY = hashlib.sha256(_KEY).digest()
_NONCE_SIZE = 16
_COMPRESSION_LEVEL = 9


def _keystream(purpose: bytes, nonce: bytes, size: int) -> bytes:
    return hashlib.shake_256(_KEY + b"\0" + purpose + b"\0" + nonce).digest(size)


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(i ^ j for i, j in zip(data, key))


def seal(data: bytes, purpose: bytes) -> bytes:
    """
    Compresses and masks `data` for storage in this fork's custom containers.
    """

    compressed = zlib.compress(data, _COMPRESSION_LEVEL)
    nonce = hashlib.blake2s(compressed, digest_size=_NONCE_SIZE, key=_BLAKE_KEY).digest()
    return nonce + _xor(compressed, _keystream(purpose, nonce, len(compressed)))


def open_sealed(data: bytes, purpose: bytes) -> bytes:
    """
    Reverses `seal`.
    """

    if len(data) < _NONCE_SIZE:
        raise ValueError("custom payload is too short")

    nonce = data[:_NONCE_SIZE]
    body = data[_NONCE_SIZE:]
    compressed = _xor(body, _keystream(purpose, nonce, len(body)))
    return zlib.decompress(compressed)
