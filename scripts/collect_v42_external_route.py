#!/usr/bin/env python3
"""Archive six completed routes alongside their accepted synthesis and simulation."""
import argparse
import json
from pathlib import Path
import shutil
import tarfile

from v42_external_flow import BASE, BUILD, ROOT, sha, write


def collect(tag):
    build = BUILD / tag
    candidate = BASE / 'candidates' / tag
    synth = json.loads((candidate / 'result.json').read_text())
    routed = json.loads((build / 'route/result.json').read_text())
    assert synth['functional_pass'] and synth['post_synth_acceptance']
    assert routed['passed'] and routed['stage'] == 'post_route'
    assert routed['rtl_sha256'] == synth['rtl_sha256']
    assert routed['source_snapshot_sha256'] == synth['source_snapshot_sha256']
    assert set(routed['tops']) == set(synth['tops']) and len(routed['tops']) == 6
    for path, digest in routed['rtl_sha256'].items():
        assert sha(ROOT / path) == digest, path
    for name, row in routed['tops'].items():
        assert row['passed'] and row['rom_audit']['passed'] and row['wns_ns'] >= .0999 and row['whs_ns'] >= 0
        invocation = json.loads((build / 'route' / name / 'invocation.json').read_text())
        assert sha(candidate / 'synthesis' / name / 'post_synth.dcp') == invocation['source_dcp_sha256'], name
        for path, digest in row['evidence_sha256'].items():
            assert sha(build / 'route' / name / path) == digest, (name, path)
    shutil.copytree(build / 'route', candidate / 'route', dirs_exist_ok=True)
    for name in ('v42_external_route.py', 'collect_v42_external_route.py', 'report_v42_external_ppa.py', 'reproduce_v42_external_route.py', 'finalize_v42_external_core.py'):
        shutil.copy2(ROOT / 'scripts' / name, candidate / 'route' / name)
    # Keep the corrected implementation/recovery tools separate from the
    # immutable RTL synthesis snapshot and the original route attempt scripts.
    with tarfile.open(candidate / 'implementation_tools.tar.gz', 'w:gz') as archive:
        for name in ('Makefile', 'README.md', 'docs/Architecture.md', 'docs/Job_Interface.md', 'docs/Verification.md'):
            archive.add(ROOT / name, arcname=name)
        for directory in ('scripts', 'tests', 'experiments/v4.2/external_job_message'):
            for path in sorted((ROOT / directory).rglob('*')):
                if path.is_file() and path.suffix in ('.py', '.tcl', '.mem') and '__pycache__' not in path.parts:
                    archive.add(path, arcname=str(path.relative_to(ROOT)))
    write(candidate / 'evidence_sha256.json', {
        str(p.relative_to(candidate)): sha(p) for p in sorted(candidate.rglob('*'))
        if p.is_file() and p.name != 'evidence_sha256.json'
    })
    write(BASE / 'routed_final.json', dict(candidate=tag, post_route_pass=True, core_timing_pass=True, io_timing_qualified=False,
          route_result_sha256=sha(candidate / 'route/result.json'),
          common_frequency_mhz=routed['common_frequency_mhz'], timing_scope=routed['timing_scope']))
    latest = json.loads((BASE / 'final.json').read_text())
    assert latest['candidate'] == tag, 'collect synthesis for this candidate first'
    latest.update(post_route_pass=True, core_timing_pass=True, io_timing_qualified=False, frequency_mhz=routed['common_frequency_mhz'],
                  route_result_sha256=sha(candidate / 'route/result.json'))
    write(BASE / 'final.json', latest)
    print('EXTERNAL_ROUTE_ARCHIVED', tag, routed['common_frequency_mhz'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tag')
    collect(p.parse_args().tag)
