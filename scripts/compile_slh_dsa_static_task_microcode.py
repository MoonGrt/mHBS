#!/usr/bin/env python3
"""Generate the data-independent static horizontal Sign program."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.static_task_microcode import *  # noqa: E402,F403


def build_program() -> tuple[list[int], list[StaticTaskToken], list[int]]:
    templates: list[int] = []
    template_ids: dict[int, int] = {}

    def tid(word: int) -> int:
        value = template_word(word)
        if value not in template_ids:
            template_ids[value] = len(templates)
            templates.append(value)
        return template_ids[value]

    def cmd(recipe: int, commit: int, mode: int) -> int:
        return command(recipe, commit, mode)

    tokens: list[StaticTaskToken] = []

    # R and H_msg.  Only R is the first issue and therefore has no wait.
    tokens.append(StaticTaskToken(
        TOKEN_SINGLE,
        tid(issue_word(cmd(RECIPE_MSG_PRF, COMMIT_R, 0), first=True)),
    ))
    tokens.append(StaticTaskToken(
        TOKEN_SINGLE,
        tid(issue_word(cmd(RECIPE_MSG_DIGEST, COMMIT_HMSG, 0))),
    ))

    # One FORS tree body.  The outer loop adds one to the six-bit tree field.
    fors_body_start = len(tokens)
    leaf0 = coordinate(group=0, item=0)
    leaf1 = coordinate(group=0, item=1)
    dual_fors_leaf = issue_word(
        cmd(RECIPE_ADDR_CHAIN, COMMIT_FORS_LEAF, MODE_FORS),
        cmd(RECIPE_ADDR_CHAIN, COMMIT_FORS_LEAF, MODE_FORS), lane1=True)
    tokens.append(StaticTaskToken(
        TOKEN_RUN, tid(dual_fors_leaf), leaf0, leaf1, 32,
        coordinate(item=2), coordinate(item=2)))
    for height, parents in ((1, 32), (2, 16), (3, 8),
                            (4, 4), (5, 2), (6, 1)):
        auth = coordinate(height=height)
        tokens.append(StaticTaskToken(
            TOKEN_SINGLE,
            tid(issue_word(cmd(RECIPE_EMIT_AUTH,
                               COMMIT_EMIT_AUTH, MODE_FORS))), auth))
        p0 = coordinate(height=height, item=0)
        p1 = coordinate(height=height, item=1)
        if parents == 1:
            parent_word = issue_word(
                cmd(RECIPE_ADDR_PARENT, COMMIT_FORS_PARENT, MODE_FORS))
            tokens.append(StaticTaskToken(
                TOKEN_SINGLE, tid(parent_word), p0))
        else:
            parent_word = issue_word(
                cmd(RECIPE_ADDR_PARENT, COMMIT_FORS_PARENT, MODE_FORS),
                cmd(RECIPE_ADDR_PARENT, COMMIT_FORS_PARENT, MODE_FORS),
                lane1=True)
            batches = parents // 2
            if batches == 1:
                tokens.append(StaticTaskToken(
                    TOKEN_SINGLE, tid(parent_word), p0, p1))
            else:
                tokens.append(StaticTaskToken(
                    TOKEN_RUN, tid(parent_word), p0, p1, batches,
                    coordinate(item=2), coordinate(item=2)))
    tokens.append(StaticTaskToken(
        TOKEN_LOOP, back_count=len(tokens) - fors_body_start,
        loop_repeats=32, delta0=coordinate(group=1),
        delta1=coordinate(group=1)))
    tokens.append(StaticTaskToken(
        TOKEN_SINGLE,
        tid(issue_word(cmd(RECIPE_LIST, COMMIT_FORS_ROOT, MODE_FORS))))
    )

    # One XMSS layer.  Its inner loop builds eight WOTS leaves; the outer
    # loop advances through all 22 hypertree layers.
    layer_body_start = len(tokens)
    leaf_body_start = len(tokens)
    chain0 = coordinate(item=0)
    chain1 = coordinate(item=1)
    dual_chain = issue_word(
        cmd(RECIPE_ADDR_CHAIN, COMMIT_WOTS_CHAIN, MODE_WOTS),
        cmd(RECIPE_ADDR_CHAIN, COMMIT_WOTS_CHAIN, MODE_WOTS), lane1=True)
    tokens.append(StaticTaskToken(
        TOKEN_RUN, tid(dual_chain), chain0, chain1, 17,
        coordinate(item=2), coordinate(item=2)))
    tokens.append(StaticTaskToken(
        TOKEN_SINGLE,
        tid(issue_word(cmd(RECIPE_ADDR_CHAIN,
                           COMMIT_WOTS_CHAIN, MODE_WOTS))),
        coordinate(item=34)))
    tokens.append(StaticTaskToken(
        TOKEN_SINGLE,
        tid(issue_word(cmd(RECIPE_LIST, COMMIT_WOTS_LEAF, MODE_WOTS))))
    )
    tokens.append(StaticTaskToken(
        TOKEN_LOOP, back_count=len(tokens) - leaf_body_start,
        loop_repeats=7, delta0=coordinate(group=1),
        delta1=coordinate(group=1)))

    for height, parents in ((1, 4), (2, 2), (3, 1)):
        auth = coordinate(height=height)
        tokens.append(StaticTaskToken(
            TOKEN_SINGLE,
            tid(issue_word(cmd(RECIPE_EMIT_AUTH,
                               COMMIT_EMIT_AUTH, MODE_XMSS))), auth))
        p0 = coordinate(height=height, item=0)
        p1 = coordinate(height=height, item=1)
        if parents == 1:
            parent_word = issue_word(
                cmd(RECIPE_ADDR_PARENT, COMMIT_XMSS_PARENT, MODE_XMSS))
            tokens.append(StaticTaskToken(
                TOKEN_SINGLE, tid(parent_word), p0))
        else:
            parent_word = issue_word(
                cmd(RECIPE_ADDR_PARENT, COMMIT_XMSS_PARENT, MODE_XMSS),
                cmd(RECIPE_ADDR_PARENT, COMMIT_XMSS_PARENT, MODE_XMSS),
                lane1=True)
            batches = parents // 2
            if batches == 1:
                tokens.append(StaticTaskToken(
                    TOKEN_SINGLE, tid(parent_word), p0, p1))
            else:
                tokens.append(StaticTaskToken(
                    TOKEN_RUN, tid(parent_word), p0, p1, batches,
                    coordinate(item=2), coordinate(item=2)))
    tokens.append(StaticTaskToken(
        TOKEN_LOOP, back_count=len(tokens) - layer_body_start,
        loop_repeats=21, delta0=coordinate(layer=1),
        delta1=coordinate(layer=1)))
    tokens.append(StaticTaskToken(TOKEN_HALT))

    if len(tokens) > 384 or len(templates) > 64:
        raise ValueError("static task image exceeds architectural limit")
    words = expand(templates, tokens)
    return templates, tokens, words


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-out", type=Path,
                        default=ROOT / "rtl/microcode/slh_dsa_128f_sign_tokens.mem")
    parser.add_argument("--template-out", type=Path,
                        default=ROOT / "rtl/microcode/slh_dsa_128f_sign_templates.mem")
    parser.add_argument("--manifest-out", type=Path,
                        default=ROOT / "manifests/programs/slh_dsa_128f_static_task_microcode.json")
    args = parser.parse_args()
    templates, tokens, words = build_program()
    args.token_out.parent.mkdir(parents=True, exist_ok=True)
    args.template_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.token_out.write_text(
        "".join(f"{token.encode():032x}\n" for token in tokens),
        encoding="ascii")
    args.template_out.write_text(
        "".join(f"{value:032x}\n" for value in templates),
        encoding="ascii")
    manifest = {
        "schema_version": "0.1.0",
        "classification": "DATA_INDEPENDENT_STATIC_HORIZONTAL_MICROCODE",
        "token_bits": 128,
        "tokens": len(tokens),
        "templates": len(templates),
        "expanded_issue_words": len(words) - 1,
        "expanded_words": len(words),
        "loop_depth": 2,
        "message_dependent_fields": [
            "WOTS chain bound", "FORS selected leaf",
            "XMSS selected leaf", "final-layer parent suppression",
        ],
    }
    args.manifest_out.write_text(json.dumps(manifest, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
