#!/usr/bin/env python3
"""Audit SLH-only software, simulations, measurements and frozen INIT images."""
import gzip,hashlib,json,math,re,tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'manifests/experiments/unified_hbs_v4.1/slh_only'
NAMES={'slh_128f','slh_192f','slh_256f'}
HUANG={'slh_128f':19584.5325,'slh_192f':32088.50325,'slh_256f':66416.67355}

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def same(a,b):return math.isclose(float(a),float(b),rel_tol=1e-11,abs_tol=1e-8)
def check(condition,message):
    if not condition:raise AssertionError(message)

def main():
    gate=json.loads((BASE/'software_gate.json').read_text())
    check(gate['passed'] and set(gate['profiles'])==NAMES,'software gate')
    for name,digest in gate['source_sha256'].items():
        check(sha(ROOT/name)==digest,'software source '+name)
    images=json.loads((BASE/'images.json').read_text())
    check(set(images['profiles'])==NAMES,'image set')
    for name,files in images['profiles'].items():
        for file,digest in files.items():check(sha(BASE/'images'/name/file)==digest,name+'/'+file)
    for result_file in (BASE/'faults').glob('*/results.json'):
        result=json.loads(result_file.read_text())
        check(result['passed'] and set(result['faults'])=={'1','3'},'fault tests')
        for fault,row in result['faults'].items():
            check(sha(result_file.parent/f'fault_{fault}.log')==row['log_sha256'],
                  'fault log '+fault)
        check(result['faults']['1']['sign_prefix']==0 and
              result['faults']['3']['sign_prefix']>=40,'failure stop ordering')
    baseline=json.loads((ROOT/'manifests/experiments/unified_hbs_v4.1/candidates/u2_area_balanced_route/ppa.json').read_text())
    candidates=[]
    for path in sorted((BASE/'candidates').glob('*/ppa.json')):
        p=json.loads(path.read_text());inputs=json.loads((path.parent/'inputs.json').read_text())
        check(p['profile_set']=='slh_only' and set(p['profiles'])==NAMES,'candidate profile set')
        check(inputs['lanes'] in (1,2,4) and inputs['unroll']==2,'lane/U2')
        evidence=json.loads((path.parent/'evidence_sha256.json').read_text())
        for name,digest in evidence.items():
            check(sha(path.parent/name)==digest,'candidate evidence '+name)
        check(sha(path.parent/'source_snapshot.tar.gz')==inputs['snapshot_sha256'],'source archive')
        with tarfile.open(path.parent/'source_snapshot.tar.gz') as archive:
            for source,digest in inputs['logic_sha256'].items():
                stream=archive.extractfile(source)
                check(stream is not None and hashlib.sha256(stream.read()).hexdigest()==digest,'RTL snapshot '+source)
        check(same(p['equivalent_slice'],p['lut']/4+p['ff']/8+
                   p['bram36_equivalent']*232.4+p['dsp']*102.4),'area formula')
        if p['stage']=='post_route':
            clock=json.loads((path.parent/'final_clock.json').read_text())
            check(same(clock['period_ns'],p['period_ns']) and clock['wns_ns']>=0.0999 and clock['whs_ns']>=0,'timing')
            status=(path.parent/'route_status.rpt').read_text()
            def route_count(label):
                match=re.search(r'# of '+label+r'\.*\s*:\s*(\d+)\s*:',status)
                check(match is not None,'route status '+label)
                return int(match[1])
            check(route_count('routable nets')==route_count('fully routed nets') and
                  route_count('nets with routing errors')==0,'complete route')
            coverage=(path.parent/'check_timing.rpt').read_text()
            for item in ('no_clock','constant_clock','pulse_width_clock',
                         'unconstrained_internal_endpoints','multiple_clock','loops','latch_loops'):
                check(re.search(r'checking '+item+r' \(0\)',coverage) is not None,
                      'timing coverage '+item)
            frozen=path.parent/'frozen/evidence.tsv'
            if frozen.exists():
                entries=dict(line.split('\t') for line in frozen.read_text().splitlines())
                check(set(entries)==NAMES and len(set(entries.values()))==1,'three INIT structures')
                for name in NAMES:check((path.parent/'frozen'/(name+'.dcp')).is_file(),'frozen checkpoint '+name)
                check(p['frozen_hardware_sha256'] in set(entries.values()),'frozen fingerprint')
                with gzip.open(path.parent/'frozen/hardware.txt.gz','rb') as structure:
                    digest=hashlib.sha256()
                    for chunk in iter(lambda:structure.read(1024*1024),b''):digest.update(chunk)
                check(digest.hexdigest()==p['frozen_hardware_sha256'],'routed structure archive')
            check(p['performance_pass']==(p.get('numerical_pass',False) and frozen.exists()),'final acceptance')
        for name,row in p['profiles'].items():
            simulation=ROOT/row['simulation'];data=json.loads(simulation.read_text())
            check(data['passed'] and data['profile']==name and data['lanes']==inputs['lanes'],'simulation '+name)
            check(sha(simulation)==row['simulation_sha256'],'simulation digest '+name)
            check(sha(simulation.with_suffix('.log'))==data['log_sha256'],'simulation log '+name)
            atp=p['equivalent_slice']*row['sign_cycles']*p['period_ns']/1e6
            check(same(row['sign_atp'],atp) and same(row['ratio'],atp/HUANG[name]),'ATP '+name)
            check(row['improved']==(atp<baseline['profiles'][name]['sign_atp']),'baseline '+name)
        check(same(p['worst_ratio'],max(r['ratio'] for r in p['profiles'].values())),'worst ATP ratio')
        candidates.append(p)
    print('SLH_ONLY_REPRODUCE_PASS',len(candidates),'candidates',
          len([c for c in candidates if c['stage']=='post_route']),'routed')

if __name__=='__main__':main()
