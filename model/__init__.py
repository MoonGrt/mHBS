"""Shared models with the selected ablation implementation.

Set MHBS_DESIGN=i, c, or t before importing model modules (default: i).
Only implementation differences live in variants; references and data are shared.
"""
import os
from pathlib import Path

DESIGN = os.environ.get("MHBS_DESIGN", "i")
if DESIGN not in ("i", "c", "t"):
    raise ValueError("MHBS_DESIGN must be i, c, or t")

__path__.insert(0, str(Path(__file__).resolve().parent / "variants" / DESIGN))
