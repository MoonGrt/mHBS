#!/usr/bin/env python3
"""Read-only RTL observers for the six-profile K2U2 cycle breakdown."""
from legacy_lane_guard import require_legacy_lanes
require_legacy_lanes()
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'manifests/experiments/unified_hbs_v4.2/external_job_message'
NAMES = ['slh_128f', 'slh_192f', 'slh_256f', 'slh_128s', 'slh_192s', 'slh_256s']

OBSERVER = r'''
 wire [1:0] prof_run,prof_transfer,prof_prepare;
 genvar prof_i;
 generate for(prof_i=0;prof_i<2;prof_i=prof_i+1)begin: prof_observe
  assign prof_run[prof_i]=!`HBS_CORE.execution_rst &&
      `HBS_CORE.lanes[prof_i].lane.hash_state==2;
  assign prof_prepare[prof_i]=!`HBS_CORE.execution_rst &&
      (`HBS_CORE.lanes[prof_i].lane.state==1 || `HBS_CORE.lanes[prof_i].lane.state==2);
  assign prof_transfer[prof_i]=!`HBS_CORE.execution_rst && (
      (`HBS_CORE.lanes[prof_i].lane.request_valid && `HBS_CORE.lanes[prof_i].lane.request_ready) ||
      (`HBS_CORE.lanes[prof_i].lane.response_valid && `HBS_CORE.lanes[prof_i].lane.response_ready) ||
      (`HBS_CORE.lanes[prof_i].lane.state==1 && `HBS_CORE.lanes[prof_i].lane.hash_ready) ||
      (`HBS_CORE.lanes[prof_i].lane.state==1 && `HBS_CORE.lanes[prof_i].lane.fixed_block && `HBS_CORE.lanes[prof_i].lane.fast_ready) ||
      (`HBS_CORE.lanes[prof_i].lane.staged_valid && `HBS_CORE.lanes[prof_i].lane.block_ready));
 end endgenerate
 integer prof_total=0,prof_hash=0,prof_xfer=0,prof_other=0;
 integer prof_lane0=0,prof_lane1=0,prof_both=0,prof_prepare_all=0,prof_prepare_overlap=0;
 integer prof_states[0:63];
 always @(posedge clk)begin
  if(rst)begin
   prof_total=0;prof_hash=0;prof_xfer=0;prof_other=0;
   prof_lane0=0;prof_lane1=0;prof_both=0;prof_prepare_all=0;prof_prepare_overlap=0;
   for(integer i=0;i<64;i=i+1)prof_states[i]=0;
  end else if(!done)begin
   prof_total=prof_total+1;
   prof_states[`HBS_CORE.state]=prof_states[`HBS_CORE.state]+1;
   if(|prof_run)prof_hash=prof_hash+1;
   else if(|prof_transfer)prof_xfer=prof_xfer+1;
   else prof_other=prof_other+1;
   if(prof_run[0])prof_lane0=prof_lane0+1;
   if(prof_run[1])prof_lane1=prof_lane1+1;
   if(&prof_run)prof_both=prof_both+1;
   if(|prof_prepare)prof_prepare_all=prof_prepare_all+1;
   if((|prof_prepare) && (|prof_run))prof_prepare_overlap=prof_prepare_overlap+1;
  end
 end
 task print_cycle_profile;begin
  $display("CYCLE_PROFILE total=%0d hash=%0d transfer=%0d other=%0d lane0=%0d lane1=%0d both=%0d prepare=%0d overlap=%0d",prof_total,prof_hash,prof_xfer,prof_other,prof_lane0,prof_lane1,prof_both,prof_prepare_all,prof_prepare_overlap);
  for(integer i=0;i<64;i=i+1)if(prof_states[i])$display("PROFILE_STATE state=%0d cycles=%0d",i,prof_states[i]);
 end endtask
'''


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(p)


def run(cmd, log, cwd):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w') as f:
        subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', default='mhbs_cycle_profile_20261002_v1')
    ap.add_argument('--jobs', type=int, default=3)
    args = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        raise ValueError('invalid tag')
    archive = ROOT / 'manifests/analysis' / args.tag
    source = archive / 'source'
    build = ROOT / 'build/analysis' / args.tag
    manifest = archive / 'inputs.json'
    if not manifest.exists():
        candidate = json.loads((BASE / 'current_core.json').read_text())['candidate']
        reference = BASE / 'candidates' / candidate
        baseline = json.loads((reference / 'simulation.json').read_text())
        files = (ROOT / 'manifests/v42_sources.txt').read_text().split()
        for file in files:
            assert sha(ROOT / file) == baseline['rtl_sha256'][file], file
        files += ['tb/integration/tb_mhbs_external.sv', 'tb/integration/tb_mhbs_verify.sv']
        files += [str(p.relative_to(ROOT)) for p in (ROOT / 'tb/integration').glob('*.svh')]
        for file in files:
            dest = source / file
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / file, dest)
        shutil.copytree(BASE / 'images', source / 'images', dirs_exist_ok=True)
        shutil.copytree(BASE / 'vectors', source / 'vectors', dirs_exist_ok=True)
        for file in ('simulation.json', 'verify/results.json'):
            dest = archive / 'baseline' / file
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(reference / file, dest)
        shutil.copy2(ROOT / 'source/sloth/SLOTH_SHAKE_CYCLE_REPORT.md', archive / 'SLOTH_SHAKE_CYCLE_REPORT.md')
        shutil.copy2(Path(__file__), archive / 'profile_mhbs_cycles.py')
        for name in ('external', 'verify'):
            tb = source / f'tb/integration/tb_mhbs_{name}.sv'
            text = tb.read_text().replace('endmodule', OBSERVER + '\nendmodule')
            marker = '$display("EXTERNAL_PASS' if name == 'external' else '$display("VERIFY_PASS'
            assert text.count(marker) == 1
            text = text.replace(marker, 'print_cycle_profile();\n   ' + marker)
            tb.write_text(text)
        write(manifest, dict(candidate=candidate, rtl=(ROOT / 'manifests/v42_sources.txt').read_text().split(),
                             source_sha256={str(p.relative_to(source)): sha(p) for p in source.rglob('*') if p.is_file()},
                             verilator=subprocess.check_output(['verilator', '--version'], text=True).strip(),
                             script_sha256=sha(Path(__file__)), baseline_sha256=sha(archive / 'baseline/simulation.json')))
    inputs = json.loads(manifest.read_text())
    for name, digest in inputs['source_sha256'].items():
        assert sha(source / name) == digest, name
    assert inputs['script_sha256'] == sha(Path(__file__)), 'use a fresh tag after changing the profiler'
    baseline = json.loads((archive / 'baseline/simulation.json').read_text())['cases']
    verify = json.loads((archive / 'baseline/verify/results.json').read_text())['profiles']

    def case(item):
        name, op = item
        key = name + '_' + op
        out = archive / 'cases' / key
        resultfile = out / 'result.json'
        if resultfile.exists():
            return key, json.loads(resultfile.read_text())
        out.mkdir(parents=True, exist_ok=True)
        vector = source / 'vectors' / name / ('sign' if op == 'verify' else op)
        cfg = json.loads((vector / 'job.json').read_text())
        n = len(bytes.fromhex(cfg['public_seed']))
        if op == 'verify':
            sig = bytes(int(x, 16) for x in (vector / 'expected.mem').read_text().split())
            nodes = out / 'vector'
            nodes.mkdir(exist_ok=True)
            (nodes / 'nodes.mem').write_text(''.join(f'{int.from_bytes(sig[i:i+n], "little"):064x}\n' for i in range(0, len(sig), n)))
            shutil.copy2(vector / 'message.mem', nodes / 'message.mem')
            vector = nodes
            params = [f'-GNODE_BYTES={n}', f'-GNODES={len(sig)//n}']
            param_names = ('public_seed', 'public_root')
            top = 'tb_mhbs_verify'
        else:
            params = [f'-GOPERATION={cfg["operation"]}']
            param_names = ('secret_seed', 'secret_prf', 'public_seed', 'randomizer', 'public_root')
            top = 'tb_mhbs_external'
        params += [f"-G{k.upper()}=256'h{int.from_bytes(bytes.fromhex(cfg[k]), 'little'):064x}" for k in param_names]
        params += [f'-GMESSAGE_BYTES={cfg["message_bytes"]}']
        obj = build / key / 'obj'
        exe = obj / ('V' + top)
        command = ['verilator', '--binary', '--timing', '-O3', '-j', '8', '-Wno-fatal', '-Wno-WIDTH', '-Wno-UNOPTFLAT',
                   '--top-module', top, *params, '--Mdir', str(obj), *inputs['rtl'], f'tb/integration/{top}.sv']
        write(out / 'command.json', dict(compile=command, config=cfg))
        if not exe.exists():
            obj.mkdir(parents=True, exist_ok=True)
            run(command, out / 'compile.log', source)
        run([str(exe), '+IMAGE=' + str(source / 'images' / name), '+VECTOR=' + str(vector)], out / 'simulation.log', source)
        log = (out / 'simulation.log').read_text()
        match = re.search(r'CYCLE_PROFILE (.*)', log)
        assert match, key
        row = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', match[1])}
        if op == 'verify':
            base = verify[name]['normal']
            expected = base['cycles']
            assert 'VERIFY_PASS accepted=1' in log
        else:
            base = baseline[key]
            expected = base['total_cycles']
            assert 'EXTERNAL_PASS' in log
        assert row['total'] == expected, (key, row['total'], expected)
        assert row['hash'] + row['transfer'] + row['other'] == expected
        assert row['lane0'] + row['lane1'] == 12 * base['permutations']
        assert row['lane0'] + row['lane1'] - row['both'] == row['hash']
        row.update(profile=name, operation=op, permutations=base['permutations'], hashes=base['hashes'], passed=True,
                   states=dict(re.findall(r'PROFILE_STATE state=(\d+) cycles=(\d+)', log)),
                   log_sha256=sha(out / 'simulation.log'), binary_sha256=sha(exe), message_bytes=cfg['message_bytes'])
        assert sum(map(int, row['states'].values())) == expected
        write(resultfile, row)
        print('PASS', key, row['total'], flush=True)
        return key, row

    rows = {}
    work = [(name, op) for name in NAMES for op in ('keygen', 'sign', 'verify')]
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        futures = {pool.submit(case, x): x for x in work}
        for f in concurrent.futures.as_completed(futures):
            key, row = f.result()
            rows[key] = row
            write(archive / 'status.json', dict(completed=len(rows), total=len(work), last=key))
    write(archive / 'results.json', dict(candidate=inputs['candidate'], passed=True, cases=rows, inputs_sha256=sha(manifest)))
    write(archive / 'SHA256.json', {str(p.relative_to(archive)): sha(p) for p in archive.rglob('*') if p.is_file() and p.name != 'SHA256.json'})


if __name__ == '__main__':
    main()
