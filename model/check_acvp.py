"""Check SHA2 SLH internal signatures against four pinned NIST ACVP cases.

Select one RTL-sized message for each 128f/128s deterministic/randomized group,
compare the complete reference signature and model-generated key/signature,
and publish ordinary eight-file RTL vectors. The downloaded source stays in
the build directory; selected cases, the upstream pin and checksums are small
enough to retain in an experiment archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request

from model.reference import slh_dsa
from model.vectors import generate_profile

COMMIT = "975de31eb83d87039ec88934fdc47d8c312b892d"
SOURCE_SHA256 = "62b42e7c27fda5de8a94aba2943ae413b59b6ea08141f3bc035b1eceae235dba"
URL = (f"https://raw.githubusercontent.com/usnistgov/ACVP-Server/{COMMIT}/"
       "gen-val/json-files/SLH-DSA-sigGen-FIPS205/internalProjection.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/sha2_models/acvp"))
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = out / "sigGen.json"
    if not source.exists():
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
            raise ValueError("NIST ACVP source checksum mismatch")
        source.write_bytes(data)
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("NIST ACVP source checksum mismatch")
    groups = json.loads(data)["testGroups"]
    selected, results = [], []
    for group in groups:
        parameter_set = group.get("parameterSet")
        if parameter_set not in ("SLH-DSA-SHA2-128f", "SLH-DSA-SHA2-128s"):
            continue
        if group.get("signatureInterface") != "internal":
            continue
        candidates = [t for t in group["tests"] if 1 <= len(t["message"])//2 <= 87]
        if not candidates:
            raise ValueError(f"No RTL-sized ACVP case in group {group['tgId']}")
        case = min(candidates, key=lambda t: (len(t["message"]), t["tcId"]))
        selected.append(dict(group={k: v for k, v in group.items() if k != "tests"}, test=case))
        started = time.monotonic()
        name = "slh_128" + parameter_set[-1]
        params = getattr(slh_dsa, "SLH_DSA_SHA2_128" + name[-1].upper())
        secret = bytes.fromhex(case["sk"])
        public = bytes.fromhex(case["pk"])
        message = bytes.fromhex(case["message"])
        expected = bytes.fromhex(case["signature"])
        random = secret[32:48] if group["deterministic"] else bytes.fromhex(case["additionalRandomness"])
        actual = slh_dsa.sign_internal(params, message, secret, random)
        if actual != expected:
            raise AssertionError(f"ACVP reference signature mismatch tcId={case['tcId']}")
        if not slh_dsa.verify_internal(params, message, expected, public):
            raise AssertionError(f"ACVP reference verification failed tcId={case['tcId']}")
        config = dict(secret_seed=secret[:16].hex(), secret_prf=secret[16:32].hex(),
                      public_seed=secret[32:48].hex(), randomizer=random.hex(),
                      identifier=bytes(16).hex(), q=0, message=message.hex())
        vector_root = out / "vectors" / f"tg{group['tgId']}_tc{case['tcId']}"
        generation = generate_profile(name, config, str(vector_root), "sha2")
        def expected_bytes(operation):
            path = vector_root / name / operation / "expected.mem"
            return bytes(int(word, 16) for word in path.read_text().split())
        if expected_bytes("sign") != expected or expected_bytes("keygen") != secret + public:
            raise AssertionError(f"ACVP recipe model output mismatch tcId={case['tcId']}")
        row = dict(profile=name, hash_backend="sha2", tgId=group["tgId"], tcId=case["tcId"],
                   deterministic=group["deterministic"], message_bytes=len(message),
                   signature_bytes=len(expected), passed=True, seconds=time.monotonic()-started,
                   vector_directory=str(vector_root / name), generation=generation)
        results.append(row)
        (out / "VALIDATION.json").write_text(json.dumps(dict(
            schema="mhbs.sha2.acvp.v1", complete=len(results)==4, passed=len(results), required=4,
            source=dict(commit=COMMIT, url=URL, sha256=SOURCE_SHA256), results=results), indent=2)+"\n")
        print("ACVP_SHA2_PASS", name, "deterministic="+str(group["deterministic"]),
              "tcId="+str(case["tcId"]), "vectors="+str(vector_root / name), flush=True)
    if len(results) != 4:
        raise AssertionError(f"Expected four ACVP cases, found {len(results)}")
    (out / "selected.json").write_text(json.dumps(selected, indent=2)+"\n")


if __name__ == "__main__":
    main()
