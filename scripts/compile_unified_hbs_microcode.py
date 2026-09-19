#!/usr/bin/env python3
"""Pack all product programs into the fixed 256 x 128-bit product ROM."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MICROCODE = ROOT / "rtl" / "microcode"
MANIFESTS = ROOT / "manifests" / "programs"
ROM_WORDS = 256
MAGIC = 0x4D484253  # ASCII "MHBS"


def read_words(name: str, bits: int) -> list[int]:
    path = MICROCODE / name
    words = [int(line.strip(), 16) for line in path.read_text().splitlines()
             if line.strip()]
    if any(word >= 1 << bits for word in words):
        raise ValueError(f"{name}: value exceeds {bits} bits")
    return words


def pair64(words: list[int]) -> list[int]:
    padded = words + ([0] if len(words) & 1 else [])
    return [padded[index] | (padded[index + 1] << 64)
            for index in range(0, len(padded), 2)]


def directory_word(*, algorithm: int, n_bytes: int, height: int,
                   token_base: int, token_count: int,
                   template_base: int, template_count: int,
                   descriptor_base: int, descriptor_count: int,
                   keygen_entry: int, sign_entry: int,
                   stateful: bool) -> int:
    fields = (
        (algorithm, 2), (int(stateful), 1), (n_bytes, 6), (height, 5),
        (token_base, 8), (token_count, 8),
        (template_base, 8), (template_count, 8),
        (descriptor_base, 8), (descriptor_count, 8),
        (keygen_entry, 9), (sign_entry, 9),
    )
    word = 0
    offset = 0
    for value, width in fields:
        if value >= 1 << width:
            raise ValueError(f"directory field {value} exceeds {width} bits")
        word |= value << offset
        offset += width
    return word


def main() -> None:
    slh_tokens = read_words("slh_dsa_128f_unified_tokens.mem", 128)
    slh_templates = read_words("slh_dsa_128f_unified_templates.mem", 128)
    slh_descriptors = read_words(
        "slh_dsa_128f_unified_descriptors.mem", 64)
    xmss_tokens = read_words("xmss_shake256_h10_w4_tokens.mem", 128)
    xmss_templates = read_words("xmss_shake256_h10_w4_templates.mem", 128)
    lms_tokens = read_words(
        "lms_shake256_h10_w4_research_tokens.mem", 128)
    lms_templates = read_words(
        "lms_shake256_h10_w4_research_templates.mem", 128)
    state_descriptors = read_words(
        "stateful_hbs_unified_descriptors.mem", 64)

    cursor = 4
    slh_token_base = cursor
    cursor += len(slh_tokens)
    xmss_token_base = cursor
    cursor += len(xmss_tokens)
    lms_token_base = cursor
    cursor += len(lms_tokens)
    slh_template_base = cursor
    cursor += len(slh_templates)
    xmss_template_base = cursor
    cursor += len(xmss_templates)
    lms_template_base = cursor
    cursor += len(lms_templates)
    slh_descriptor_base = cursor
    slh_descriptor_records = pair64(slh_descriptors)
    cursor += len(slh_descriptor_records)
    state_descriptor_base = cursor
    state_descriptor_records = pair64(state_descriptors)
    cursor += len(state_descriptor_records)
    if cursor > ROM_WORDS:
        raise ValueError(f"unified image needs {cursor} records, max {ROM_WORDS}")

    image = [0] * ROM_WORDS
    image[0] = (MAGIC << 96) | (1 << 88) | (3 << 80) | cursor
    image[1] = directory_word(
        algorithm=0, n_bytes=16, height=6, stateful=False,
        token_base=slh_token_base, token_count=len(slh_tokens),
        template_base=slh_template_base,
        template_count=len(slh_templates),
        descriptor_base=slh_descriptor_base,
        descriptor_count=len(slh_descriptors), keygen_entry=11, sign_entry=0)
    image[2] = directory_word(
        algorithm=1, n_bytes=32, height=10, stateful=True,
        token_base=xmss_token_base, token_count=len(xmss_tokens),
        template_base=xmss_template_base,
        template_count=len(xmss_templates),
        descriptor_base=state_descriptor_base,
        descriptor_count=64, keygen_entry=0, sign_entry=9)
    image[3] = directory_word(
        algorithm=2, n_bytes=32, height=10, stateful=True,
        token_base=lms_token_base, token_count=len(lms_tokens),
        template_base=lms_template_base,
        template_count=len(lms_templates),
        descriptor_base=state_descriptor_base + 32,
        descriptor_count=64, keygen_entry=0, sign_entry=9)

    regions = (
        (slh_token_base, slh_tokens),
        (xmss_token_base, xmss_tokens),
        (lms_token_base, lms_tokens),
        (slh_template_base, slh_templates),
        (xmss_template_base, xmss_templates),
        (lms_template_base, lms_templates),
        (slh_descriptor_base, slh_descriptor_records),
        (state_descriptor_base, state_descriptor_records),
    )
    for base, words in regions:
        image[base:base + len(words)] = words

    rendered = "".join(f"{word:032x}\n" for word in image)
    path = MICROCODE / "unified_hbs_product_rom.mem"
    path.write_text(rendered, encoding="ascii")
    rendered64 = "".join(
        f"{half:016x}\n"
        for word in image
        for half in (word & ((1 << 64) - 1), word >> 64)
    )
    (MICROCODE / "unified_hbs_product_rom64.mem").write_text(
        rendered64, encoding="ascii")
    manifest = {
        "schema_version": "1.0.0",
        "name": "micro-hbs-three-profile-product-rom",
        "runtime_writable": False,
        "word_bits": 128,
        "capacity_words": ROM_WORDS,
        "used_words": cursor,
        "used_bits": cursor * 128,
        "capacity_bits": ROM_WORDS * 128,
        "physical_layout": "512x64 single-port, two cycles per logical word",
        "sha256": hashlib.sha256(rendered.encode("ascii")).hexdigest(),
        "profiles": {
            "slh_dsa_shake_128f": {"directory": 1},
            "xmss_shake256_h10_w4": {"directory": 2},
            "lms_shake_h10_w4_research": {"directory": 3},
        },
        "regions": {
            "slh_tokens": [slh_token_base, len(slh_tokens)],
            "xmss_tokens": [xmss_token_base, len(xmss_tokens)],
            "lms_tokens": [lms_token_base, len(lms_tokens)],
            "slh_templates": [slh_template_base, len(slh_templates)],
            "xmss_templates": [xmss_template_base, len(xmss_templates)],
            "lms_templates": [lms_template_base, len(lms_templates)],
            "slh_descriptors_128": [slh_descriptor_base,
                                    len(slh_descriptor_records)],
            "stateful_descriptors_128": [state_descriptor_base,
                                         len(state_descriptor_records)],
        },
    }
    (MANIFESTS / "unified_hbs_product_rom_v1.0.0.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
