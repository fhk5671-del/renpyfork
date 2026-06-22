from __future__ import annotations

import argparse
import hashlib
import importlib.util
import pickle
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_blobstore():
    path = ROOT / "renpy" / "blobstore.py"
    spec = importlib.util.spec_from_file_location("_rnx_blobstore", path)

    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def premium_digest(game_id: str, tier: int, kind: str) -> str:
    text = f"rnx-premium-v1|{kind}|{game_id}|{tier}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def premium_marker_path(game_id: str, tier: int) -> str:
    return f"premium/{premium_digest(game_id, tier, 'path')[:24]}.dat"


def premium_marker_token(game_id: str, tier: int) -> bytes:
    return ("rnx:" + premium_digest(game_id, tier, "token")).encode("utf-8")


def parse_member(value: str) -> tuple[Path, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("members must use source=archive/path")

    source, archive_name = value.split("=", 1)

    if not source or not archive_name:
        raise argparse.ArgumentTypeError("members must use source=archive/path")

    return Path(source), archive_name.replace("\\", "/").lstrip("/")


def add_member(blobstore, handle, index: dict, archive_name: str, data: bytes) -> None:
    sealed = blobstore.seal(data, blobstore.ARCHIVE_MEMBER_PURPOSE)
    offset = handle.tell()
    handle.write(sealed)
    index[archive_name] = [(offset, len(sealed), len(data))]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a game-specific premium RNX pack.")
    parser.add_argument("--tier", type=int, required=True, choices=(10, 15))
    parser.add_argument("--game-id", required=True, help="Game-specific id, usually config.save_directory.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--add", action="append", default=[], type=parse_member, metavar="SOURCE=ARCHIVE_PATH")
    args = parser.parse_args()

    blobstore = load_blobstore()
    index = {}

    args.out.parent.mkdir(parents=True, exist_ok=True)

    with args.out.open("wb") as handle:
        handle.write(blobstore.ARCHIVE_HEADER_PLACEHOLDER)
        add_member(blobstore, handle, index, premium_marker_path(args.game_id, args.tier), premium_marker_token(args.game_id, args.tier))

        for source, archive_name in args.add:
            add_member(blobstore, handle, index, archive_name, source.read_bytes())

        index_offset = handle.tell()
        index_data = blobstore.seal(pickle.dumps(index, pickle.HIGHEST_PROTOCOL), blobstore.ARCHIVE_INDEX_PURPOSE)
        handle.write(index_data)
        handle.seek(0)
        handle.write(blobstore.ARCHIVE_HEADER % (index_offset, len(index_data)))

    print(args.out)


if __name__ == "__main__":
    main()
