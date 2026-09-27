#!/usr/bin/env python3
"""Validate and export ABI 4 images and their fixed-job demonstration vectors."""
from pathlib import Path
import sys
import json
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.unified_hbs import compile_image, Machine
from tests.test_unified_hbs import default_job, memory
from model.profiles import PROFILES
from verify_seven_models import require_gate


def main():
    gate = require_gate()
    results = {}
    for name, p in PROFILES.items():
        image = compile_image(name)
        job, message = default_job(name)
        machine = Machine(image, job)
        kg = machine.run(False)
        kg_count = (machine.hashes, machine.permutations)
        sg = machine.run(True, message)
        sg_count = (machine.hashes, machine.permutations)
        if p.family == "slh":
            kat = json.loads(next((ROOT / "tests/kat").glob(f"slh_dsa_shake_{p.n*8}f_siggen_acvp_tc*.json")).read_text())
            assert kg == bytes.fromhex(kat["sk"]+kat["pk"])
            assert hashlib.sha256(sg).hexdigest() == kat["signature_sha256"]
        elif p.omega == 4:
            stem = "xmss" if p.family == "xmss" else "lms_shake"
            assert kg == memory(stem+"_stateful_keygen_bytes.mem")
            assert sg == memory(stem+"_stateful_sign_bytes.mem")
        for kind, words, width in (("tokens", image.tokens, 128),
                                  ("templates", image.templates, 128),
                                  ("descriptors", image.descriptors, 64)):
            target = ROOT / f"rtl/microcode/mhbs_{name}_{kind}.mem"
            target.write_text("".join(f"{x:0{width//4}x}\n" for x in words))
        for kind, data in (("keygen", kg), ("sign", sg), ("message", message)):
            (ROOT / f"tb/vectors/mhbs_{name}_{kind}.mem").write_text("".join(f"{x:02x}\n" for x in data))
        results[name] = dict(n=image.n, stateful=image.stateful, family=p.family,
            omega=p.omega, chains=p.chains, len1=p.len1, len2=p.len2,
            h=p.h, hp=p.hp, d=p.d, k=p.k, a=p.a, m=p.m, target=p.target, lanes=p.lanes,
            recipe_mask=sum(1 << shape for shape in {((word >> 56) & 15) for word in image.descriptors if word >> 60 == 1}),
            chain_recipe_mask=sum(1 << shape for shape in {
                (image.descriptors[(word >> shift) & 255] >> 56) & 15
                for word in image.descriptors if word >> 60 == 4 for shift in (52, 44)}),
            cache_policy="selected_authentication_path" if image.stateful else "transient_tree",
            tokens=len(image.tokens), templates=len(image.templates), descriptors=len(image.descriptors),
            keygen_entry=image.entry(False), sign_entry=image.entry(True),
            keygen_bytes=len(kg), sign_bytes=len(sg), message_bytes=len(message),
            keygen_hashes=kg_count[0], keygen_permutations=kg_count[1],
            sign_hashes=sg_count[0], sign_permutations=sg_count[1],
            keygen_sha256=hashlib.sha256(kg).hexdigest(), sign_sha256=hashlib.sha256(sg).hexdigest(),
            secret=job.secret.hex(), prf=job.prf.hex(), public=job.public.hex(),
            random=job.random.hex(), identifier=job.identifier.hex(), initial_q=job.q)
        print(f"MODEL_GATE_PASS {name} keygen={kg_count} sign={sg_count}", flush=True)
    report = dict(abi_version=4,
        model_sha256=hashlib.sha256((ROOT / "model/unified_hbs.py").read_bytes()).hexdigest(),
        profiles=results)
    (ROOT / "manifests/experiments/unified_hbs_v4/model_gate.json").write_text(json.dumps(report, indent=2)+"\n")


if __name__ == "__main__":
    main()
