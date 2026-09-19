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
    images = all_images()
    for image in images:
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

    # Product SLH core uses one immutable dual-entry image.  Sign descriptors
    # are also valid for Keygen; descriptor zero only carries output metadata,
    # while RTL enforces the operation-specific output bound.
    sign = next(image for image in images if "sign" in image.name)
    keygen = next(image for image in images if "keygen" in image.name)
    template_bias = len(sign.templates)
    if template_bias + len(keygen.templates) > 64:
        raise ValueError("combined SLH template image exceeds six-bit index")
    adjusted_keygen_tokens = []
    for word in keygen.tokens:
        token_kind = word >> 126
        if token_kind in (0, 1):
            template = (word >> 120) & 0x3F
            word = (word & ~(0x3F << 120)) \
                | ((template + template_bias) << 120)
        adjusted_keygen_tokens.append(word)
    combined_tokens = sign.tokens + tuple(adjusted_keygen_tokens)
    combined_templates = sign.templates + keygen.templates
    combined_outputs = {
        "tokens": (args.output_dir / "slh_dsa_128f_unified_tokens.mem",
                   render_words(combined_tokens, 128)),
        "templates": (
            args.output_dir / "slh_dsa_128f_unified_templates.mem",
            render_words(combined_templates, 128)),
        "descriptors": (
            args.output_dir / "slh_dsa_128f_unified_descriptors.mem",
            render_words(sign.descriptors, 64)),
    }
    for path, text in combined_outputs.values():
        path.write_text(text, encoding="ascii")
    manifest["unified_image"] = {
        "name": "slh-dsa-shake-128f-keygen-sign",
        "runtime_writable": False,
        "operation_entries": {"sign": 0, "keygen": len(sign.tokens)},
        "tokens": len(combined_tokens),
        "templates": len(combined_templates),
        "descriptors": len(sign.descriptors),
        "files": {
            key: path.relative_to(ROOT).as_posix()
            for key, (path, _text) in combined_outputs.items()
        },
    }

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
