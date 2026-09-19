#!/usr/bin/env python3
"""Compile the immutable SHAKE-128f Sign and Keygen macrocode images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.generic_hbs_macrocode import (  # noqa: E402
    all_images,
    image_manifest,
    render_words,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "rtl" / "microcode",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=(ROOT / "manifests" / "programs"
                 / "slh_dsa_128f_generic_macrocode.json"),
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": "0.1.0", "images": []}
    for image in all_images():
        stem = "slh_dsa_128f_sign_macro" if "sign" in image.name \
            else "slh_dsa_128f_keygen_macro"
        outputs = {
            "tokens": (args.output_dir / f"{stem}_tokens.mem",
                       render_words(image.tokens, 128)),
            "templates": (args.output_dir / f"{stem}_templates.mem",
                          render_words(image.templates, 128)),
            "descriptors": (args.output_dir / f"{stem}_descriptors.mem",
                            render_words(image.descriptors, 64)),
        }
        for path, text in outputs.values():
            path.write_text(text, encoding="ascii")
        record = image_manifest(image)
        record["files"] = {
            key: path.relative_to(ROOT).as_posix()
            for key, (path, _text) in outputs.items()
        }
        manifest["images"].append(record)

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
