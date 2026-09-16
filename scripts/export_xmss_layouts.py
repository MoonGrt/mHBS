#!/usr/bin/env python3
"""Export the supported XMSS Sign JSON layouts as immutable RTL images."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.layout_lowering import lower_layouts  # noqa: E402


SOURCE = ROOT / "microcode/xmss/xmss_shake256_h10_w4_sign.json"
KAT = ROOT / "tests/kat/xmss_shake256_10_256_idx5.json"
OUTPUT_DIR = ROOT / "manifests/programs/rtl_images"
LAYOUT_HEX = OUTPUT_DIR / "xmss_xmss_shake256_h10_w4_sign_layouts.hex"
COMPONENT_HEX = OUTPUT_DIR / "xmss_xmss_shake256_h10_w4_sign_components.hex"
MANIFEST = ROOT / "manifests/programs/xmss_sign_layout_image_v0.1.0.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    document = json.loads(SOURCE.read_text(encoding="utf-8"))
    vector = json.loads(KAT.read_text(encoding="utf-8"))
    message_bytes = len(bytes.fromhex(vector["message"]))
    field_slots = {
        "sk_seed": 248,
        "pub_seed": 249,
        "sk_prf": 250,
        "root": 251,
        "index": 252,
        "message": 253,
    }
    result = lower_layouts(
        document, [0, 1, 2, 3, 4, 5, 6, 7, 9, 10],
        job_field_slots=field_slots,
        job_field_lengths={"message": message_bytes},
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LAYOUT_HEX.write_text(result.layout_hex(), encoding="ascii")
    COMPONENT_HEX.write_text(result.component_hex(), encoding="ascii")
    record = {
        "schema_version": 1,
        "artifact_kind": "micro_hbs_layout_component_image",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": _sha256(SOURCE),
        "kat": str(KAT.relative_to(ROOT)),
        "kat_sha256": _sha256(KAT),
        "layout_ids": [item.layout_id for item in result.layouts],
        "layout_count": len(result.layouts),
        "component_count": len(result.components),
        "layout_word_bits": 128,
        "component_word_bits": 192,
        "image_sha256": result.sha256,
        "job_field_slots": field_slots,
        "frozen_message_bytes": message_bytes,
        "layout_hex": {
            "path": str(LAYOUT_HEX.relative_to(ROOT)),
            "sha256": _sha256(LAYOUT_HEX),
            "line_count": len(result.layouts),
        },
        "component_hex": {
            "path": str(COMPONENT_HEX.relative_to(ROOT)),
            "sha256": _sha256(COMPONENT_HEX),
            "line_count": len(result.components),
        },
        "execution_contract": {
            "offline_export_only": True,
            "immutable_during_job": True,
            "runtime_task_ingress": False,
            "runtime_hash_ingress": False,
        },
        "limitations": [
            "Tree layout 8 is handled by the separate TreeHash descriptor path.",
            "The KAT message length is frozen because variable-length Job message descriptors are not yet implemented.",
            "Expression/context words used by tree parent pipelines remain outside this component image.",
        ],
    }
    MANIFEST.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"exported {len(result.layouts)} layouts / {len(result.components)} "
        f"components ({result.sha256})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
