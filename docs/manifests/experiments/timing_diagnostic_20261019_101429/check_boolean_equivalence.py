#!/usr/bin/env python3
"""Independent two-state exhaustions for the recycle/ready candidate.

No project model, ROM, recipe executor, simulator, or external solver is used.
The ready model includes contradictory tag-equality abstractions deliberately:
proving this superset avoids depending on legal request scheduling assumptions.
This establishes combinational ready/receive factoring and one metadata-register
transition only; it is not a substitute for functional hash/sign simulation.
"""
from hashlib import sha256
from itertools import product
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def ready_equivalence():
    count = 0
    # A real state enum cannot be IDLE and FIXED_WAIT simultaneously.
    for idle, bridge in [(True, False), (False, True), (False, False)]:
        for (rst, batch, valid, fixed, pending, again, recycle,
             busy0, busyb, resp_valid, resp_ready, batch_resp_ready,
             pending0, pendingb, resp0, respb, tag_valid, batch_valid
             ) in product([False, True], repeat=18):
            scalar = bridge or (not batch and idle and valid and fixed)
            mode = batch or scalar
            ready = not rst and not recycle
            accept = pending and not rst and not again and mode and ready
            retire = resp_valid and ((bridge and resp_ready) if scalar
                                     else batch_resp_ready)
            slot0 = ((not busy0 or (retire and resp0)) and
                     (not pending or not pending0))
            slotb = (tag_valid and (not busyb or (retire and respb)) and
                     (not pending or not pendingb))
            incoming = (not rst and mode and (not pending or accept) and
                        (slot0 if scalar else slotb))
            old_scalar = idle and (not fixed or (not batch and incoming))
            old_batch = incoming and not scalar
            old_receive = ((idle and valid) if scalar else batch_valid) and incoming

            queue_open = not rst and (not pending or (not again and ready))
            scalar_capacity = queue_open and not busy0 and (not pending or not pending0)
            batch_capacity = (queue_open and tag_valid and
                              (not busyb or (resp_valid and batch_resp_ready and respb)) and
                              (not pending or not pendingb))
            new_scalar = idle and (not fixed or (not batch and valid and scalar_capacity))
            new_batch = batch and not bridge and batch_capacity
            new_receive = ((idle and valid and fixed and not batch and scalar_capacity) or
                           (batch_valid and new_batch))
            assert (old_scalar, old_batch, old_receive) == (new_scalar, new_batch, new_receive)
            count += 1
    return count


def recycle_equivalence():
    rows = []
    # All legal P > 1 / U combinations, including U > 2 and a full traversal.
    for pipeline in range(2, 25):
        for unroll in range(1, 25):
            rounds = pipeline * unroll
            if rounds > 24 or 24 % rounds:
                continue
            count = 0
            # For the final stage (s = P-1), its source metadata comes directly
            # from s-1 = P-2. Base is held on bubbles; valid always advances.
            # Test every encoded base value, not just reachable round bases.
            for rst, previous_valid, previous_base, held_final_base in product(
                    [False, True], [False, True], range(32), range(32)):
                next_final_valid = False if rst else previous_valid
                next_final_base = (previous_base if not rst and previous_valid
                                   else held_final_base)
                next_recycle = (False if rst else
                                previous_valid and previous_base + rounds < 24)
                legacy_next_recycle = next_final_valid and next_final_base + rounds < 24
                assert next_recycle == legacy_next_recycle
                count += 1
            rows.append({"pipeline": pipeline, "unroll": unroll, "rounds": rounds,
                         "metadata_transition_cases": count, "status": "passed"})
    return rows


def main():
    sources = [line.strip() for line in (ROOT / "sources.txt").read_text().splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    assert len(sources) == 8
    before = {name: digest(ROOT / name) for name in sources}
    recycle = recycle_equivalence()
    summary = {
        "status": "passed",
        "method": "independent exhaustive two-state Python equations",
        "ready_receive_cases": ready_equivalence(),
        "ready_receive_outputs": ["request_ready", "batch_request_ready", "receive"],
        "ready_assumption": "IDLE and FIXED_WAIT are mutually exclusive enum values",
        "recycle_legal_configurations": recycle,
        "recycle_metadata_transition_cases": sum(row["metadata_transition_cases"] for row in recycle),
        "recycle_inductive_base": "reset sets final stage_valid and registered recycle to zero",
        "recycle_inductive_step": "final-stage source metadata advances from P-2 on the same edge as recycle",
        "limitations": ["two-state only; X/Z propagation is not exhaustively proved",
                        "equation proof is manually tied to inspected RTL, not parser-based equivalence",
                        "does not replace full hash/output/signature-cache simulation or routed STA"],
        "rtl_sha256": before,
        "sources_sha256": digest(ROOT / "sources.txt"),
        "baseline_recipe_sha256": digest(OUT / "recipe.before.sv"),
        "proof_script_sha256": digest(Path(__file__).resolve()),
    }
    summary["source_unchanged_during_proof"] = before == {
        name: digest(ROOT / name) for name in sources}
    assert summary["source_unchanged_during_proof"]
    (OUT / "BOOLEAN_EQUIVALENCE.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": summary["status"],
                      "ready_receive_cases": summary["ready_receive_cases"],
                      "recycle_configurations": len(recycle),
                      "recycle_metadata_transition_cases": summary["recycle_metadata_transition_cases"]}))


if __name__ == "__main__":
    main()
