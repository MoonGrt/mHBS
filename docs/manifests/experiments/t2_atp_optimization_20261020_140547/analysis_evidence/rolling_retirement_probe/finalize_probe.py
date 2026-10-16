from pathlib import Path
import json, hashlib, shutil, re, subprocess

RUN = Path(__file__).resolve().parent
ROOT = next(p for p in RUN.parents if (p/'sources.txt').is_file())
FINAL = ROOT/'build/t2_atp_optimization/candidate_20261020_140547'
data = json.loads((RUN/'RESULTS.json').read_text())
meta = json.loads((RUN/'SOURCE.json').read_text())
source = RUN/'source'
base = Path(meta['baseline_run'])/'source'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

for row in data['tests']:
    vector_dir = Path('tb/vectors')/row['profile']/'sign'
    names = sorted(p.relative_to(source/vector_dir) for p in (source/vector_dir).rglob('*') if p.is_file())
    row['vectors_sha256'] = {str(n): sha(source/vector_dir/n) for n in names}
    row['vectors_equal_to_baseline'] = all(sha(base/vector_dir/n) == h for n, h in [(Path(k), v) for k, v in row['vectors_sha256'].items()])
data['reproduction_script_sha256'] = sha(RUN/'run_probe.py')
data['passed'] = data['passed'] and all(row['vectors_equal_to_baseline'] for row in data['tests'])
data['final_candidate_run'] = str(FINAL)
data['final_source_manifest_sha256'] = sha(FINAL/'SOURCE.json')
data['matches_final_candidate_rtl'] = {
    n: sha(source/n) == sha(FINAL/'source'/n)
    for n in meta['rtl_sha256']
}
def code_sha(path):
    text = re.sub(r'//[^\n]*|/\*.*?\*/', '', path.read_text(), flags=re.S)
    return hashlib.sha256(''.join(text.split()).encode()).hexdigest()
data['matches_final_candidate_rtl_ignoring_comments_whitespace'] = {
    n: code_sha(source/n) == code_sha(FINAL/'source'/n)
    for n in meta['rtl_sha256']
}
data['final_rtl_sha256'] = {n: sha(FINAL/'source'/n) for n in meta['rtl_sha256']}
data['source_binding_note'] = 'Nine RTL files byte-identical; executor differs only in two comment lines describing the identical roll_free expression. Exact diff retained, with all10 comment/whitespace-normalized code digests equal. Probe frozen source was never modified to imitate U5 byte identity.'
assert data['passed'] and data['source_unchanged']
assert all(data['matches_final_candidate_rtl_ignoring_comments_whitespace'].values())
(RUN/'RESULTS.json').write_text(json.dumps(data, indent=2)+'\n')
lines = [
    '# U4 registered rolling retirement probe / U5 source binding', '',
    '6/6 full Sign pass. Output/cache and Hash/permutation checks pass; frozen probe source unchanged. No Vivado.', '',
    '| P/U | Profile | U4 cycles | Probe cycles | Delta | Delta % |',
    '|---|---|---:|---:|---:|---:|',
]
for row in data['tests']:
    lines.append('| P{}U1 | {} | {} | {} | {} | {:.6f} |'.format(row['p'], row['profile'], row['baseline_cycles'], row['cycles'], row['cycles_delta'], row['cycles_change_pct']))
lines += [
    '',
    'Only RTL change from U4: roll_free = ~pipe_active. A returning slot becomes eligible after registered retirement on the next edge; previously idle slots remain eligible immediately. This removes response-valid/tag from the free-slot priority encoder and downstream request-tag/context-ready feedback. No extra Hash work, lane, or P/U specialization. P1 does not use rolling batch scheduling.', '',
    'Maximum measured cycle cost: 0.213518%. Area/frequency benefit still requires synthesis/physical measurement; no frequency claim follows from these simulations.', '',
    data['source_binding_note']+' SHA256 identities and raw-log references are retained in RESULTS.json. Detailed simulation logs remain only in the build run directory.', '',
    'U4 source manifest SHA256: '+meta['baseline_source_manifest_sha256'],
    'Probe source manifest SHA256: '+sha(RUN/'SOURCE.json'),
    'U5 source manifest SHA256: '+data['final_source_manifest_sha256'],
]
(RUN/'RESULTS.md').write_text('\n'.join(lines)+'\n')
archive = ROOT/'docs/manifests/experiments/t2_atp_optimization_20261020_140547/analysis_evidence/rolling_retirement_probe'
archive.mkdir(parents=True, exist_ok=True)
diff = subprocess.run(['diff', '-u', '--label', 'probe/rtl/executor/executor.sv', '--label', 'U5/rtl/executor/executor.sv', str(source/'rtl/executor/executor.sv'), str(FINAL/'source/rtl/executor/executor.sv')], capture_output=True, text=True).stdout
(RUN/'comments_to_U5.patch').write_text(diff)
names = ['RESULTS.md', 'RESULTS.json', 'SOURCE.json', 'run_probe.py', 'finalize_probe.py', 'comments_to_U5.patch']
for name in names:
    shutil.copy2(RUN/name, archive/name)
shutil.copy2(ROOT/'tmp/t2_rolling_retire_candidate/from_U4.patch', archive/'from_U4.patch')
names += ['from_U4.patch']
(archive/'SHA256.json').write_text(json.dumps({n: sha(archive/n) for n in names}, indent=2)+'\n')
print(json.dumps({'passed': data['passed'], 'all_code_matches_U5': all(data['matches_final_candidate_rtl_ignoring_comments_whitespace'].values()), 'archive': str(archive)}, indent=2))
