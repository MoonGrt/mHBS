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


def relocate_tokens(words: tuple[int, ...], template_delta: int) -> tuple[int, ...]:
    """Relocate ISSUE-template indices while leaving LOOP/HALT untouched."""
    relocated: list[int] = []
    for word in words:
        kind = word >> 126
        if kind < 2:
            template = (word >> 120) & 0x3F
            template += template_delta
            if template >= 64:
                raise ValueError("relocated template index exceeds six bits")
            word = (word & ~(0x3F << 120)) | (template << 120)
        relocated.append(word)
    return tuple(relocated)


def relocate_image_entries(word: int, token_delta: int) -> int:
    keygen = ((word >> 47) & 0x1FF) + token_delta
    sign = ((word >> 38) & 0x1FF) + token_delta
    if keygen >= 512 or sign >= 512:
        raise ValueError("relocated operation entry exceeds nine bits")
    return (word & ~((0x1FF << 47) | (0x1FF << 38))
            | (keygen << 47) | (sign << 38))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.mkdir(parents=True, exist_ok=True)
    images = all_stateful_images()
    for image in images:
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

    # The production executor selects the profile at run time.  Keep equal,
    # dense descriptor banks.  Control is deliberately no longer
    # shared: XMSS spells out 67 TREE_PUSH operations for its L-tree, whereas
    # LMS spells out the endpoint-list and leaf Hashes.  This is the central
    # guarantee that tree selection lives in microcode rather than RTL.
    if len(images) != 2:
        raise ValueError("the unified stateful image requires XMSS and LMS")
    descriptor_bank_words = len(images[0].descriptors)
    if descriptor_bank_words == 0 or any(
        len(image.descriptors) != descriptor_bank_words for image in images
    ):
        raise ValueError("stateful descriptor banks must be equal and nonempty")
    second_descriptors = list(images[1].descriptors)
    second_descriptors[0] = relocate_image_entries(
        second_descriptors[0], len(images[0].tokens))
    combined_descriptors = images[0].descriptors + tuple(second_descriptors)
    if len(combined_descriptors) != 2 * descriptor_bank_words:
        raise ValueError("combined stateful descriptor image has wrong size")
    # Legacy combined token/template files are not consumed by the product
    # packer after ABI v0.4, but remain executable by the reference core.
    # Relocate LMS token entries and template indices into the second banks.
    combined_tokens = images[0].tokens + relocate_tokens(
        images[1].tokens, len(images[0].templates))
    (OUT / "stateful_hbs_unified_tokens.mem").write_text(
        render(combined_tokens, 128), encoding="ascii"
    )
    (OUT / "stateful_hbs_unified_templates.mem").write_text(
        render(images[0].templates + images[1].templates, 128),
        encoding="ascii"
    )
    (OUT / "stateful_hbs_unified_descriptors.mem").write_text(
        render(combined_descriptors, 64), encoding="ascii"
    )
    unified_manifest = {
        "schema_version": "0.4.0",
        "name": "stateful-hbs-unified",
        "runtime_writable": False,
        "profile_select": {"0": images[0].name, "1": images[1].name},
        "descriptor_bank_words": descriptor_bank_words,
        "tokens": sum(len(image.tokens) for image in images),
        "templates": sum(len(image.templates) for image in images),
        "descriptors": len(combined_descriptors),
        "tree_control_in_microcode": True,
    }
    (MANIFEST / "stateful_hbs_unified_macro_v0.4.0.json").write_text(
        json.dumps(unified_manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
