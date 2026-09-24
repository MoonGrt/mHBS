#!/usr/bin/env python3
"""Audit v4.1 archived evidence; refuse to turn partial PPA into acceptance."""
from pathlib import Path
import argparse,hashlib,json,math,re,sys,tarfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model.profiles import PROFILES
from model.autonomous_hbs import ProgramImage
from rom_initialization import mapping
BASE=ROOT/'manifests/experiments/unified_hbs_v4.1'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(ok,message):
    if not ok:raise AssertionError(message)
def eq(a,b):return math.isclose(float(a),float(b),rel_tol=1e-11,abs_tol=1e-9)
def resource(text,label):
    match=re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d,.]+)\s*\|',text)
    check(match is not None,'missing resource '+label)
    return float(match[1].replace(',',''))
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--allow-incomplete',action='store_true');args=parser.parse_args()
    gate=json.loads((BASE/'software_gate.json').read_text());check(gate['pass'],'software gate')
    for path,digest in gate['sources'].items():check(sha(ROOT/path)==digest,'software source '+path)
    images=json.loads((BASE/'images.json').read_text())['profiles']
    for name,data in images.items():
        folder=BASE/'images'/name;ProgramImage.read(folder).decode()
        for path,digest in data['image_sha256'].items():check(sha(folder/path)==digest,'ROM image '+name+'/'+path)
    print('V4.1 software gate / images: PASS')
    final_path=BASE/'final.json'
    if not final_path.exists():
        print('V4.1 performance acceptance: INCOMPLETE (no final manifest)')
        return 0 if args.allow_incomplete else 2
    final=json.loads(final_path.read_text());check(final['version']=='v4.1' and final['abi_version']==4,'version/ABI')
    folder=BASE/final['archive'];inputs=json.loads((folder/'inputs.json').read_text());ppa=json.loads((folder/'ppa.json').read_text())
    check(sha(folder/'source_snapshot.tar.gz')==inputs['snapshot_sha256'],'snapshot digest')
    with tarfile.open(folder/'source_snapshot.tar.gz','r:gz') as tar:
        for path,digest in inputs['source_sha256'].items():check(hashlib.sha256(tar.extractfile(path).read()).hexdigest()==digest,'snapshot source '+path)
    for path,digest in final['evidence_sha256'].items():check(sha(BASE/path)==digest,'evidence '+path)
    util=(folder/'utilization.rpt').read_text()
    lut,ff,bram,dsp=[resource(util,s) for s in ('Slice LUTs','Slice Registers','Block RAM Tile','DSPs')]
    area=lut/4+ff/8+bram*232.4+dsp*102.4
    check(eq(area,ppa['equivalent_slice']),'area formula')
    clock=json.loads((folder/'final_clock.json').read_text());period=clock['period_ns']
    check(eq(period*10,round(period*10)) and clock['wns_ns']>=.0999 and clock['whs_ns']>=0,'clock margin')
    check(eq(period,ppa['period_ns']),'common clock')
    timing=(folder/'timing_summary.rpt').read_text();row=re.search(r'WNS\(ns\).*?\n\s*[- ]+\n([^\n]+)',timing).group(1).split()
    check(all(float(row[i])>=0 for i in (0,4,8)) and all(float(row[i])==0 for i in (1,5,9)),'setup/hold/pulse')
    route=(folder/'route_status.rpt').read_text()
    for label in ('Number of nets with routing errors','Number of unrouted nets'):
        m=re.search(re.escape(label)+r'\s*:\s*(\d+)',route);check(m and int(m[1])==0,label)
    coverage=(folder/'check_timing.rpt').read_text()
    for label in ('no_clock','constant_clock','multiple_clock','unconstrained_internal_endpoints','loops','latch_loops'):
        m=re.search(r'checking '+label+r' \((\d+)\)',coverage);check(m and int(m[1])==0,'coverage '+label)
    old=json.loads((ROOT/'manifests/experiments/unified_hbs_final.json').read_text())['profiles']
    ceilings={a:old[b]['sign_atp'] for a,b in [('slh_128f','slh'),('xmss_omega4','xmss'),('lms_omega4','lms')]}
    structural=set();binaries=set()
    for name,p in PROFILES.items():
        data=ppa['profiles'][name];sim_path=ROOT/data['simulation'];sim=json.loads(sim_path.read_text())
        check(sha(sim_path)==data['simulation_sha256'] and sha(sim_path.with_suffix('.log'))==sim['log_sha256'],'simulation digest '+name)
        check(sim['passed'] and sim['logic_sha256']==inputs['logic_sha256'],'simulation hardware '+name)
        binaries.add(sim['binary_sha256'])
        for kind in ('keygen','sign'):check(sim[kind+'_hashes']==images[name][kind+'_hashes'] and sim[kind+'_permutations']==images[name][kind+'_permutations'],'hash counts '+name)
        atp=area*sim['sign_cycles']*period/1e6
        check(eq(atp,data['sign_atp']) and atp<p.target,'paper ATP '+name)
        check(name not in ceilings or atp<=ceilings[name],'V3 regression '+name)
        futil=(folder/'frozen'/(name+'_utilization.rpt')).read_text()
        check(all(resource(util,k)==resource(futil,k) for k in ('Slice LUTs','Slice Registers','LUT as Memory','Block RAM Tile','DSPs')),'identical area '+name)
        expected=mapping(name)
        rows=dict(line.split('\t') for line in (folder/'frozen'/(name+'_init.tsv')).read_text().splitlines())
        check(set(rows)==set(expected),'ROM cells '+name)
        check(all(int(rows[k].split("'h")[1],16)==int(v.split("'h")[1],16) for k,v in expected.items()),'physical INIT '+name)
        structural.add(final['hardware_sha256'][name])
        print(f'{name:14s} common_area={area:.3f} MHz={1000/period:.3f} KG={sim["keygen_cycles"]:,} Sign={sim["sign_cycles"]:,} ATP={atp:,.3f} PASS')
    check(len(structural)==1 and len(binaries)==1,'same hardware/netlist/simulation binary')
    check(next(iter(structural))==sha(folder/'frozen/hardware.txt'),'frozen structure digest')
    check(final['functional_pass'] and final['performance_pass'],'final acceptance flags')
    print('V4.1 seven-profile common-hardware acceptance: PASS')
    return 0
if __name__=='__main__':sys.exit(main())
