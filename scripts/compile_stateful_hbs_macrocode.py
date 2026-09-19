#!/usr/bin/env python3
"""Emit immutable dual-entry XMSS/LMS macrocode images."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.stateful_hbs_macrocode import all_stateful_images  # noqa: E402


OUT = ROOT / "rtl" / "microcode"
MANIFEST = ROOT / "manifests" / "programs"


def render(words: tuple[int, ...], bits: int) -> str:
    digits = bits // 4
    return "".join(f"{word:0{digits}x}\n" for word in words)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.mkdir(parents=True, exist_ok=True)
    for image in all_stateful_images():
        stem = image.name.replace("-", "_")
        (OUT / f"{stem}_tokens.mem").write_text(
            render(image.tokens, 128), encoding="ascii"
        )
        (OUT / f"{stem}_templates.mem").write_text(
            render(image.templates, 128), encoding="ascii"
        )
        (OUT / f"{stem}_descriptors.mem").write_text(
            render(image.descriptors, 64), encoding="ascii"
        )
        manifest = {
            "schema_version": "0.2.0",
            "name": image.name,
            "family": image.family.name,
            "runtime_writable": False,
            "operation_entries": {
                "keygen": image.keygen_entry,
                "sign": image.sign_entry,
            },
            "tokens": len(image.tokens),
            "templates": len(image.templates),
            "descriptors": len(image.descriptors),
            "keygen_output_bytes": image.keygen_output_bytes,
            "sign_output_bytes": image.sign_output_bytes,
        }
        (MANIFEST / f"{stem}_macro_v0.2.0.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
