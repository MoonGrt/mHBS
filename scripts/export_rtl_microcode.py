#!/usr/bin/env python3
"""Export verified μHBS JSON programs as deterministic RTL readmemh images."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.rtl_image_export import (  # noqa: E402
    RTL_PROGRAM_LIMIT_WORDS,
    export_programs,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Offline assemble/verify JSON microcode and emit one 64-bit "
            "$readmemh hex image per source plus a deterministic manifest."
        )
    )
    parser.add_argument(
        "sources",
        nargs="*",
        type=Path,
        help="JSON sources; default discovers microcode/*/*.json",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=ROOT,
        help="root used for stable relative paths (default: μHBS root)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "manifests/programs/rtl_images",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "manifests/programs/rtl_images_v0.1.0.json",
    )
    parser.add_argument(
        "--capacity-words",
        type=int,
        default=RTL_PROGRAM_LIMIT_WORDS,
        help="configured program-store capacity, at most 512",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    project_root = args.project_root.resolve()
    sources = args.sources or sorted(project_root.glob("microcode/*/*.json"))
    try:
        manifest = export_programs(
            sources,
            args.output_dir,
            args.manifest,
            project_root,
            capacity_words=args.capacity_words,
        )
    except (OSError, ValueError) as exc:
        print(f"export failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"exported {manifest['image_count']} verified images to "
        f"{args.output_dir} (capacity={manifest['capacity_words']} words)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
