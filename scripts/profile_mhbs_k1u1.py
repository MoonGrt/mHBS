#!/usr/bin/env python3
"""Measure an isolated single-lane U1 derivative of the frozen K2U2 experiment."""
import argparse
import concurrent.futures
import difflib
import json
from pathlib import Path
import re
import shutil
import subprocess

from profile_mhbs_cycles import ROOT, NAMES, sha, write, run


def prepare(parent, archive):
    source = archive / 'source'
    old = json.loads((parent / 'inputs.json').read_text())
    for name, digest in old['source_sha256'].items():
        assert sha(parent / 'source' / name) == digest, name
    shutil.copytree(parent / 'source', source)
    shutil.copytree(parent / 'baseline', archive / 'baseline')
    shutil.copy2(parent / 'results.json', archive / 'k2u2_results.json')
    shutil.copy2(parent / 'SLOTH_SHAKE_CYCLE_REPORT.md', archive / 'SLOTH_SHAKE_CYCLE_REPORT.md')
    changes = []

    def edit(name, fn):
        p = source / name
        before = p.read_text()
        after = fn(before)
        assert after != before, name
        p.write_text(after)
        changes.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='a/'+name, tofile='b/'+name))

    def core(s):
        s = s.replace('lane_index<2;', 'lane_index<LANES;')
        s = s.replace('.FIXED_BANK_WRITES(1)', '.FIXED_BANK_WRITES(0)')
        s = s.replace('initial if(LANES!=2 || UNROLL!=2) $error("Production core requires K2U2");', '''
    initial if(LANES!=1 || UNROLL!=1) $error("This experimental derivative requires K1U1");
    assign lane_ready[1]=0;
    assign lane_valid[1]=0;
    assign lane_error[1]=0;
    assign lane_value[1]=0;
    assign lane_capture[1]=0;
    assign lane_list0[1]=0;
    assign lane_list1[1]=0;
    assign lane_hashes[1]=0;
    assign lane_permutations[1]=0;
    always @(posedge clk) if(!execution_rst)
        assert(!active_mask[1] && !launch_pending[1] && !response_pending[1])
            else $fatal(1,"K1 scheduled a nonexistent lane");
''')
        return s

    edit('rtl/top/mhbs_hbs.sv', core)
    for which in ('external', 'verify'):
        def tb(s, which=which):
            s = s.replace('mhbs_top #(', 'mhbs_top #(.LANES(1),.UNROLL(1),')
            s = s.replace('lane<2;', 'lane<1;').replace('l<2;', 'l<1;')
            s = s.replace('round_index+2>=24', 'round_index+1>=24')
            s = s.replace('prof_i<2;', 'prof_i<1;')
            zero = 'initial begin observed_hashes[1]=0;observed_permutations[1]=0;end' if which == 'external' else 'initial begin hashes[1]=0;permutations[1]=0;end'
            s = s.replace('endmodule', '''
 assign prof_run[1]=0;
 assign prof_transfer[1]=0;
 assign prof_prepare[1]=0;
 ''' + zero + '\nendmodule')
            return s
        edit(f'tb/integration/tb_mhbs_{which}.sv', tb)
    edit('tb/integration/mhbs_shared_store_check.svh', lambda s: re.sub(
        r'\) \|\|\n \(`HBS_CORE\.lanes\[1\].*?input_length\);', ');', s, flags=re.S))
    edit('tb/integration/mhbs_route_source_check.svh', lambda s: s.replace('chain_cursor+2<', 'chain_cursor+1<'))
    (archive / 'k1u1.patch').write_text(''.join(changes))
    shutil.copy2(Path(__file__), archive / Path(__file__).name)
    write(archive / 'inputs.json', dict(candidate=old['candidate']+'_k1u1_experimental', lanes=1, unroll=1,
          parent_inputs_sha256=sha(parent / 'inputs.json'), parent_results_sha256=sha(parent / 'results.json'),
          rtl=old['rtl'], source_sha256={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()},
          script_sha256=sha(Path(__file__)), verilator=subprocess.check_output(['verilator','--version'],text=True).strip()))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', default='mhbs_cycle_profile_k1u1_20261002_v1')
    ap.add_argument('--parent', default='mhbs_cycle_profile_20261002_v1')
    ap.add_argument('--jobs', type=int, default=3)
    ap.add_argument('--profiles', nargs='+', choices=NAMES, default=NAMES)
    args = ap.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9_-]+',args.tag)
    archive = ROOT / 'manifests/analysis' / args.tag
    if not (archive / 'inputs.json').exists():
        archive.mkdir(parents=True, exist_ok=True)
        prepare(ROOT / 'manifests/analysis' / args.parent, archive)
    inputs = json.loads((archive / 'inputs.json').read_text())
    assert sha(Path(__file__)) == inputs['script_sha256'], 'use a new tag for a changed experiment'
    source = archive / 'source'
    for name, digest in inputs['source_sha256'].items():
        assert sha(source / name) == digest, name
    reference = json.loads((archive / 'k2u2_results.json').read_text())['cases']

    def case(task):
        name, op = task
        key = name+'_'+op
        out = archive / 'cases' / key
        result = out / 'result.json'
        if result.exists():
            return key,json.loads(result.read_text())
        out.mkdir(parents=True,exist_ok=True)
        vector = source/'vectors'/name/('sign' if op=='verify' else op)
        cfg = json.loads((vector/'job.json').read_text())
        n = len(bytes.fromhex(cfg['public_seed']))
        if op=='verify':
            sig=bytes(int(x,16) for x in (vector/'expected.mem').read_text().split())
            v=out/'vector';v.mkdir(exist_ok=True)
            (v/'nodes.mem').write_text(''.join(f'{int.from_bytes(sig[i:i+n],"little"):064x}\n' for i in range(0,len(sig),n)))
            shutil.copy2(vector/'message.mem',v/'message.mem');vector=v
            params=[f'-GNODE_BYTES={n}',f'-GNODES={len(sig)//n}']
            keys=('public_seed','public_root');top='tb_mhbs_verify'
        else:
            params=[f'-GOPERATION={cfg["operation"]}']
            keys=('secret_seed','secret_prf','public_seed','randomizer','public_root');top='tb_mhbs_external'
        params += [f"-G{k.upper()}=256'h{int.from_bytes(bytes.fromhex(cfg[k]),'little'):064x}" for k in keys]
        params += [f'-GMESSAGE_BYTES={cfg["message_bytes"]}']
        obj=ROOT/'build/analysis'/args.tag/key/'obj';exe=obj/('V'+top)
        cmd=['verilator','--binary','--timing','-O3','-j','8','-Wno-fatal','-Wno-WIDTH','-Wno-UNOPTFLAT','--top-module',top,*params,'--Mdir',str(obj),*inputs['rtl'],f'tb/integration/{top}.sv']
        write(out/'command.json',dict(compile=cmd,config=cfg))
        if not exe.exists():
            obj.mkdir(parents=True,exist_ok=True);run(cmd,out/'compile.log',source)
        run([str(exe),'+IMAGE='+str(source/'images'/name),'+VECTOR='+str(vector)],out/'simulation.log',source)
        log=(out/'simulation.log').read_text()
        row={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',re.search(r'CYCLE_PROFILE (.*)',log)[1])}
        passed=re.search(r'(?:EXTERNAL_PASS|VERIFY_PASS) (.*)',log)
        assert passed,key
        counts={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',passed[1])}
        assert counts['hashes']==reference[key]['hashes'],(key,counts)
        assert counts['permutations']==reference[key]['permutations'],(key,counts)
        assert op!='verify' or counts['accepted']==1
        assert row['total']==counts.get('total',counts.get('cycles'))
        assert row['hash']+row['transfer']+row['other']==row['total']
        assert row['lane0']==row['hash']==24*counts['permutations']
        assert row['lane1']==row['both']==0
        row.update(profile=name,operation=op,lanes=1,unroll=1,hashes=counts['hashes'],permutations=counts['permutations'],
                   k2u2_total=reference[key]['total'],passed=True,message_bytes=cfg['message_bytes'],
                   states=dict(re.findall(r'PROFILE_STATE state=(\d+) cycles=(\d+)',log)),
                   log_sha256=sha(out/'simulation.log'),binary_sha256=sha(exe))
        assert sum(map(int,row['states'].values()))==row['total']
        write(result,row);print('PASS',key,row['total'],flush=True)
        return key,row

    rows={}
    tasks=[(p,op) for p in args.profiles for op in ('keygen','sign','verify')]
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        futures=[pool.submit(case,t) for t in tasks]
        for f in concurrent.futures.as_completed(futures):
            key,row=f.result();rows[key]=row
            write(archive/'status.json',dict(completed=len(rows),total=len(tasks),last=key))
    write(archive/'results.json',dict(candidate=inputs['candidate'],lanes=1,unroll=1,passed=True,cases=rows,inputs_sha256=sha(archive/'inputs.json')))
    write(archive/'SHA256.json',{str(p.relative_to(archive)):sha(p) for p in archive.rglob('*') if p.is_file() and p.name!='SHA256.json'})


if __name__=='__main__':
    main()
