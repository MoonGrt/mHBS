"""Deterministic offline export of JSON microcode to RTL ``$readmemh`` files.

This module is intentionally a build-time utility.  It assembles and verifies
complete immutable programs; it does not define a runtime task/hash ingress.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from model.microcode_assembler import load_and_assemble
from model.microcode_verifier import verify_image


RTL_PROGRAM_LIMIT_WORDS = 512
WORD_WIDTH_BITS = 64


class RtlImageExportError(ValueError):
    """Raised when an image cannot be represented by the RTL program store."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _project_relative(path: Path, project_root: Path, label: str) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError as exc:
        raise RtlImageExportError(
            f"{label} must be inside project root: {resolved}"
        ) from exc


def render_readmemh(words: Iterable[int]) -> bytes:
    """Return one address-ordered, fixed-width 64-bit word per ASCII line."""

    lines: list[str] = []
    for index, word in enumerate(words):
        if not isinstance(word, int) or not 0 <= word < (1 << WORD_WIDTH_BITS):
            raise RtlImageExportError(
                f"word {index} does not fit {WORD_WIDTH_BITS} bits: {word!r}"
            )
        lines.append(f"{word:016x}\n")
    if not lines:
        raise RtlImageExportError("cannot export an empty program")
    return "".join(lines).encode("ascii")


def default_hex_name(source: Path, project_root: Path) -> str:
    """Derive a collision-resistant stable name from ``microcode/<family>``."""

    relative = Path(_project_relative(source, project_root, "source"))
    try:
        microcode_relative = relative.relative_to("microcode")
    except ValueError as exc:
        raise RtlImageExportError(
            f"source must be below microcode/: {relative.as_posix()}"
        ) from exc
    return "_".join(microcode_relative.with_suffix("").parts) + ".hex"


def build_image_artifact(
    source: Path,
    hex_path: Path,
    project_root: Path,
    *,
    capacity_words: int = RTL_PROGRAM_LIMIT_WORDS,
) -> tuple[bytes, dict[str, Any]]:
    """Build, but do not write, one verified readmemh image and manifest entry."""

    if not 1 <= capacity_words <= RTL_PROGRAM_LIMIT_WORDS:
        raise RtlImageExportError(
            "capacity_words must be in the Phase-1 range 1..512"
        )

    source = source.resolve()
    project_root = project_root.resolve()
    source_relative = _project_relative(source, project_root, "source")
    hex_relative = _project_relative(hex_path, project_root, "hex output")
    document = json.loads(source.read_text(encoding="utf-8"))
    image = load_and_assemble(source)
    verification = verify_image(image)
    word_count = int(image["word_count"])
    if word_count > capacity_words:
        raise RtlImageExportError(
            f"program has {word_count} words, exceeds configured "
            f"{capacity_words}-word capacity"
        )

    hex_bytes = render_readmemh(image["words"])
    source_parts = Path(source_relative).parts
    family = source_parts[1] if len(source_parts) >= 3 else "unknown"
    entry: dict[str, Any] = {
        "artifact_kind": "micro_hbs_readmemh_image",
        "program_family": family,
        "program_name": image["name"],
        "micro_isa_version": image["micro_isa_version"],
        "source_schema_version": document.get("schema_version"),
        "source": source_relative,
        "source_sha256": _sha256(source.read_bytes()),
        "entry_word": int(image["entry"]),
        "word_width_bits": WORD_WIDTH_BITS,
        "word_count": word_count,
        "image_bytes": int(image["image_bytes"]),
        "capacity_words": capacity_words,
        "unused_capacity_words": capacity_words - word_count,
        "program_sha256": image["sha256"],
        "readmemh": {
            "path": hex_relative,
            "sha256": _sha256(hex_bytes),
            "line_count": word_count,
            "address_order": "ascending_from_zero",
            "digits_per_word": 16,
            "radix": "hex",
            "padding_words_emitted": 0,
        },
        "verification": verification,
        "execution_contract": {
            "offline_export_only": True,
            "immutable_program_image": True,
            "runtime_task_ingress": False,
            "runtime_hash_ingress": False,
        },
    }
    return hex_bytes, entry


def export_programs(
    sources: Iterable[Path],
    output_directory: Path,
    manifest_path: Path,
    project_root: Path,
    *,
    capacity_words: int = RTL_PROGRAM_LIMIT_WORDS,
) -> dict[str, Any]:
    """Verify the complete source set before writing any stable artifacts.

    All images are built before any file is written, so a bad/oversized program
    cannot leave a partially refreshed committed image set.
    """

    project_root = project_root.resolve()
    output_directory = output_directory.resolve()
    manifest_path = manifest_path.resolve()
    source_list = sorted(
        (Path(source).resolve() for source in sources),
        key=lambda path: _project_relative(path, project_root, "source"),
    )
    if not source_list:
        raise RtlImageExportError("no microcode sources selected")

    pending: list[tuple[Path, bytes, dict[str, Any]]] = []
    seen_output_names: set[str] = set()
    for source in source_list:
        output_name = default_hex_name(source, project_root)
        if output_name in seen_output_names:
            raise RtlImageExportError(f"duplicate output name: {output_name}")
        seen_output_names.add(output_name)
        hex_path = output_directory / output_name
        hex_bytes, entry = build_image_artifact(
            source,
            hex_path,
            project_root,
            capacity_words=capacity_words,
        )
        pending.append((hex_path, hex_bytes, entry))

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "manifest_version": "0.1.0",
        "artifact_kind": "micro_hbs_rtl_program_image_set",
        "generator": "scripts/export_rtl_microcode.py",
        "word_width_bits": WORD_WIDTH_BITS,
        "capacity_words": capacity_words,
        "image_count": len(pending),
        "images": [entry for _, _, entry in pending],
        "execution_contract": {
            "generation_phase": "offline",
            "runtime_software_sequencing_required": False,
            "runtime_task_ingress": False,
            "runtime_hash_ingress": False,
        },
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")

    # Paths are constrained to the project root before this point.  Delay all
    # writes until every source has assembled and verified successfully.
    output_directory.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    for hex_path, hex_bytes, _ in pending:
        hex_path.write_bytes(hex_bytes)
    manifest_path.write_bytes(manifest_bytes)
    return manifest
