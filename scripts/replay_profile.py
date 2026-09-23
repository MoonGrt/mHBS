#!/usr/bin/env python3
"""Verify and extract one accepted source snapshot into a fresh replay directory."""
import argparse,hashlib,json,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('profile');ap.add_argument('--destination',type=Path)
    ap.add_argument('--run',choices=['rtl-profile-test','rtl-unit-test','synth-profile','route-profile'])
    a=ap.parse_args();archive=ROOT/'manifests/experiments/unified_hbs_v4'
    d=json.loads((archive/'final.json').read_text())['profiles'][a.profile]
    source=archive/d['archive'];inp=json.loads((source/'inputs.json').read_text())
    snapshot=source/'source_snapshot.tar.gz'
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest()==inp['snapshot_sha256']
    dest=(a.destination or ROOT/'build/replay'/a.profile).resolve()
    if dest.exists():raise SystemExit(f'Replay destination already exists: {dest}; choose a fresh --destination')
    with tarfile.open(snapshot,'r:gz') as tar:
        for member in tar.getmembers():
            path=dest/member.name
            if not member.isfile() or not path.resolve().is_relative_to(dest):raise ValueError('unsafe snapshot member')
            data=tar.extractfile(member).read()
            assert hashlib.sha256(data).hexdigest()==inp['source_sha256'][member.name]
        dest.mkdir(parents=True)
        for member in tar.getmembers():
            path=dest/member.name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(tar.extractfile(member).read())
    (dest/'build').mkdir(exist_ok=True)
    common=['make',f'PROFILE={a.profile}',f'UNROLL={d["unroll"]}',f'LANES={d["lanes"]}']
    print(f'Verified snapshot extracted to {dest}',flush=True)
    if a.run:
        targets=['rtl-profile-test','synth-profile','route-profile'] if a.run=='route-profile' else ['rtl-profile-test','synth-profile'] if a.run=='synth-profile' else ['compile-microcode','rtl-unit-test'] if a.run=='rtl-unit-test' else [a.run]
        for target in targets:subprocess.run(common+[target],cwd=dest,check=True)
    else:print('Next: '+ ' '.join(common+['rtl-profile-test']),flush=True)
if __name__=='__main__':main()
