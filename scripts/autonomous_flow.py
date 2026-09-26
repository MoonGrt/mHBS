#!/usr/bin/env python3
"""v4.1 common-hardware build, simulation and immutable evidence capture."""
from pathlib import Path
import argparse,concurrent.futures,gzip,hashlib,json,re,shutil,subprocess,sys,tarfile,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model.slh_only import SLH_PROFILES
BASE=ROOT/'manifests/experiments/unified_hbs_v4.1'
ACTIVE=BASE/'slh_only'
BUILD=ROOT/'build/v4.1'

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()
def sources():return (ROOT/'manifests/unified_sources.txt').read_text().splitlines()
def logic():return {p:sha(ROOT/p) for p in sources()}
def index_policy():
    return 'guarded' if 'uhbs_stateful_index_guard guard' in (ROOT/'rtl/top/uhbs_hbs.sv').read_text() else 'fixed_q_no_guard'
def logic_id(hashes):return hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()[:16]
def write(path,obj):Path(path).write_text(json.dumps(obj,indent=2)+'\n')
def run(cmd,log):
    print('RUN',str(log.relative_to(ROOT)),flush=True)
    started=time.monotonic()
    with log.open('w') as f:subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
    write(log.with_suffix('.execution.json'),dict(command=cmd,elapsed_seconds=time.monotonic()-started))
def sim(args):
    tag=f'u{args.unroll}_l{args.lanes}_s{args.swap}'
    identity=dict(logic=logic(),bench=sha(ROOT/'tb/integration/tb_uhbs_autonomous.sv'),unroll=args.unroll,lanes=args.lanes,swap=args.swap)
    folder=BUILD/('sim_'+tag+'_'+logic_id(identity['logic']));folder.mkdir(parents=True,exist_ok=True)
    binary=folder/'Vtb_uhbs_autonomous'
    stamp=folder/'compile.json'
    if not binary.exists() or not stamp.exists() or json.loads(stamp.read_text())!=identity:
        run(['verilator','--binary','--timing','-O3','-j',str(args.jobs),'-Wno-fatal','-Wno-WIDTH','-Wno-UNOPTFLAT','--top-module','tb_uhbs_autonomous',f'-GUNROLL={args.unroll}',f'-GLANES={args.lanes}',f'-GSWAP={args.swap}','--Mdir',str(folder),*sources(),'tb/integration/tb_uhbs_autonomous.sv'],BUILD/('compile_'+tag+'.log'))
        write(stamp,identity)
    names=list(SLH_PROFILES) if args.profile=='all' else [args.profile]
    if args.message_cases:names += list(json.loads((BASE/'message_cases.json').read_text()))
    if args.boundaries:names += []
    out=ACTIVE/'simulations'/logic_id(identity['logic'])/tag
    if args.replay:out=out/'replay'
    out.mkdir(parents=True,exist_ok=True)
    def one(name):
        image=(ACTIVE/'images'/name if (ACTIVE/'images'/name).is_dir()
               else BASE/'images'/name);log=out/(name+'.log')
        options=['+REPLAYS=2','+INTERRUPT=1'] if args.replay else []
        result_path=log.with_suffix('.json')
        if result_path.exists() and log.exists():
            previous=json.loads(result_path.read_text())
            if (previous.get('passed') and previous['logic_sha256']==identity['logic']
                    and previous['bench_sha256']==identity['bench']
                    and previous['log_sha256']==sha(log)
                    and previous.get('reset_replay')==args.replay
                    and previous['image_sha256']=={p.name:sha(p) for p in image.glob('*.mem')}):
                print('SIM_CACHED',name,flush=True)
                return
        if log.exists() or result_path.exists():
            history=out/'attempts'/(name+'_'+str(time.time_ns()));history.mkdir(parents=True)
            for old in (log,result_path,log.with_suffix('.execution.json')):
                if old.exists():shutil.copy2(old,history/old.name)
        run([str(binary),'+IMAGE='+str(image.relative_to(ROOT)),*options],log)
        text=log.read_text();m=re.search(r'AUTONOMOUS_PASS .*?boot_cycles=(\d+) keygen_cycles=(\d+) sign_cycles=(\d+) hash=(\d+) permutations=(\d+)',text)
        if not m:raise RuntimeError('No simulation PASS: '+name)
        kg=re.search(r'AUTONOMOUS_KEYGEN cycles=(\d+) hashes=(\d+) permutations=(\d+)',text)
        result=dict(version='v4.1',abi_version=4,index_policy=index_policy(),tool_version=subprocess.check_output(['verilator','--version'],text=True).strip(),profile=name,passed=True,lanes=args.lanes,unroll=args.unroll,swap=args.swap,reset_replay=args.replay,
            logic_sha256=identity['logic'],bench_sha256=identity['bench'],binary_sha256=sha(binary),log_sha256=sha(log),
            image_sha256={p.name:sha(p) for p in image.glob('*.mem')},
            boot_cycles=int(m[1]),keygen_cycles=int(m[2]),sign_cycles=int(m[3]),sign_hashes=int(m[4]),sign_permutations=int(m[5]),keygen_hashes=int(kg[2]),keygen_permutations=int(kg[3]))
        write(log.with_suffix('.json'),result)
        print('SIM_PASS',name,result['keygen_cycles'],result['sign_cycles'],flush=True)
    with concurrent.futures.ThreadPoolExecutor(min(4,args.jobs)) as pool:list(pool.map(one,names))

def capture(args):
    folder=BUILD/args.tag;folder.mkdir(parents=True,exist_ok=True)
    baseline=ACTIVE/'candidates'/args.baseline/'ppa.json'
    baseline_data=json.loads(baseline.read_text())
    if not baseline_data.get('performance_pass'):
        raise RuntimeError('Optimization baseline must have passed routed acceptance')
    paths=set(sources()+['manifests/unified_sources.txt','Makefile','manifests/experiments/unified_hbs_final.json','manifests/experiments/unified_hbs_v4/model_gate.json','manifests/experiments/unified_hbs_v4/boundary_counts.json','manifests/experiments/unified_hbs_v4/comparison.json','manifests/experiments/unified_hbs_v4.1/author_update.json'])
    paths.add(str(baseline.relative_to(ROOT)))
    if (BASE/'area_baseline.json').exists():paths.add(str((BASE/'area_baseline.json').relative_to(ROOT)))
    for directory in ('model','scripts','tests','tb','experiments/v4.1'):
        paths.update(str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*') if p.is_file() and p.suffix in ('.py','.sv','.svh','.mem','.json','.tcl'))
    paths.update(str(p.relative_to(ROOT)) for p in BASE.rglob('*') if p.is_file() and ('images' in p.parts or p.name in ('images.json','software_gate.json','baseline.json')))
    hashes={p:sha(ROOT/p) for p in sorted(paths)}
    snapshot=folder/'source_snapshot.tar.gz'
    if (folder/'inputs.json').exists():
        previous=json.loads((folder/'inputs.json').read_text())
        if previous['source_sha256']!=hashes or previous['lanes']!=args.lanes or previous['unroll']!=args.unroll:
            raise RuntimeError('Candidate tag already contains different sources; use a new --tag: '+args.tag)
        if not snapshot.exists() or sha(snapshot)!=previous['snapshot_sha256']:
            raise RuntimeError('Existing candidate snapshot is missing or changed: '+args.tag)
        print('CAPTURE_UNCHANGED',args.tag)
        return
    with tarfile.open(snapshot,'w:gz') as tar:
        for p in hashes:tar.add(ROOT/p,arcname=p)
    write(folder/'inputs.json',dict(version='v4.1',abi_version=4,profile_set='slh_only',lanes=args.lanes,unroll=args.unroll,baseline=str(baseline.relative_to(ROOT)),baseline_sha256=sha(baseline),logic_sha256=logic(),source_sha256=hashes,snapshot_sha256=sha(snapshot),part='xc7a200tffg1156-3',tool='Vivado 2025.2',timing_scope='OOC_INTERNAL_REGISTER_PATHS',comparison='NON_STRICT_FIPS205_VS_SPHINCS_PLUS'))

def prepare_route(args):
    source=BUILD/args.tag;target=BUILD/(args.tag+'_route')
    inputs=json.loads((source/'inputs.json').read_text())
    if sha(source/'source_snapshot.tar.gz')!=inputs['snapshot_sha256']:
        raise RuntimeError('Source snapshot changed')
    target.mkdir(parents=True,exist_ok=True)
    for name in ('inputs.json','source_snapshot.tar.gz','post_synth.dcp','rom_cells.tsv','synth_seconds.txt','synthesis.json'):
        if not (source/name).exists():continue
        if (target/name).exists() and sha(target/name)!=sha(source/name):
            raise RuntimeError('Refuse to overwrite route inputs: '+str(target/name))
        shutil.copy2(source/name,target/name)
    flow=ROOT/'experiments/v4.1/route.tcl'
    if (target/'route_flow.tcl').exists() and sha(target/'route_flow.tcl')!=sha(flow):
        raise RuntimeError('Route flow changed; use a new candidate tag')
    shutil.copy2(flow,target/'route_flow.tcl')
    print('ROUTE_PREPARED',target.name)

def collect(args):
    folder=BUILD/args.tag
    inputs=json.loads((folder/'inputs.json').read_text())
    assert sha(folder/'source_snapshot.tar.gz')==inputs['snapshot_sha256']
    text=(folder/'utilization.rpt').read_text()
    def amount(label):
        m=re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d,.]+)\s*\|',text)
        if not m:raise ValueError('Missing '+label)
        return float(m[1].replace(',',''))
    lut,ff,ram,bram,dsp=[amount(x) for x in ('Slice LUTs','Slice Registers','LUT as Memory','Block RAM Tile','DSPs')]
    area=lut/4+ff/8+bram*232.4+dsp*102.4
    period=json.loads((folder/'final_clock.json').read_text())['period_ns'] if args.route else 10.0
    baseline_path=ROOT/inputs.get('baseline',str((BASE/'candidates/u2_area_balanced_route/ppa.json').relative_to(ROOT)))
    if 'baseline_sha256' in inputs and sha(baseline_path)!=inputs['baseline_sha256']:
        raise RuntimeError('Captured comparison baseline changed')
    baseline=json.loads(baseline_path.read_text())['profiles']
    huang={'slh_128f':19584.5325,'slh_192f':32088.50325,'slh_256f':66416.67355}
    profiles={}
    for name,p in SLH_PROFILES.items():
        path=ACTIVE/'simulations'/logic_id(inputs['logic_sha256'])/f'u{inputs["unroll"]}_l{inputs["lanes"]}_s0'/(name+'.json')
        data=json.loads(path.read_text())
        assert data['passed'] and data['logic_sha256']==inputs['logic_sha256'] and sha(path.with_suffix('.log'))==data['log_sha256']
        atp=area*data['sign_cycles']*period/1e6
        profiles[name]=dict(boot_cycles=data['boot_cycles'],keygen_cycles=data['keygen_cycles'],sign_cycles=data['sign_cycles'],sign_atp=atp,keygen_atp=area*data['keygen_cycles']*period/1e6,huang_atp=huang[name],baseline_atp=baseline[name]['sign_atp'],improved=atp<baseline[name]['sign_atp'],ratio=atp/huang[name],simulation=str(path.relative_to(ROOT)),simulation_sha256=sha(path))
    result=dict(version='v4.1',tag=args.tag,stage='post_route' if args.route else 'post_synth',lut=int(lut),ff=int(ff),lutram=int(ram),bram36_equivalent=bram,dsp=int(dsp),equivalent_slice=area,period_ns=period,frequency_mhz=1000/period,profiles=profiles,inputs_sha256=sha(folder/'inputs.json'),worst_ratio=max(d['ratio'] for d in profiles.values()),performance_pass=False)
    # Acceptance additionally requires route, timing, coverage and frozen-image structural proofs.
    result['profile_set']='slh_only'
    result['frequency_basis']='post_route_margin_checked' if args.route else 'normalized_only'
    timing=(folder/'timing_summary.rpt').read_text()
    m=re.search(r'Worst Slack\s+([-\d.]+)ns',timing)
    result['wns_ns']=float(m[1]) if m else None
    if args.route:
        clock=json.loads((folder/'final_clock.json').read_text());result['timing']=clock
        result['numerical_pass']=all(x['improved'] for x in profiles.values())
    write(folder/'ppa.json',result)
    target=ACTIVE/'candidates'/args.tag;target.mkdir(parents=True,exist_ok=True)
    write(target/'ppa.json',result)
    shutil.copy2(folder/'inputs.json',target/'inputs.json')
    archive(args.tag)
    print(json.dumps({k:v for k,v in result.items() if k!='profiles'},indent=2))
    for name,r in profiles.items():print(name,round(r['sign_atp'],3),round(r['ratio'],4))

def archive(tag):
    """Keep a candidate self-contained outside the disposable build directory."""
    folder=BUILD/tag;target=ACTIVE/'candidates'/tag
    target.mkdir(parents=True,exist_ok=True)
    names=('inputs.json','source_snapshot.tar.gz','ppa.json','synthesis.json',
           'synth_seconds.txt','rom_cells.tsv','utilization.rpt',
           'utilization_hierarchical.rpt','timing_summary.rpt',
           'post_place_timing.rpt','route_status.rpt','check_timing.rpt',
           'final_clock.json','constraints.xdc','route_flow.tcl',
           'post_synth.dcp','post_route_final_clock.dcp')
    files=[folder/name for name in names if (folder/name).is_file()]
    files += [p for p in (folder/'frozen').rglob('*') if p.is_file() and p.name!='hardware.txt'] if (folder/'frozen').exists() else []
    files += [p for p in (folder/'verification').rglob('*') if p.is_file()]
    log_names=([tag+'_synth.log'] if not tag.endswith('_route') else
               [tag+'.log',tag.removesuffix('_route')+'_freeze.log'])
    for log_name in log_names:
        log=BUILD/log_name
        if log.is_file():files.append(log)
    for source in files:
        relative=source.relative_to(folder) if source.is_relative_to(folder) else Path(source.name)
        dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists() and sha(dest)!=sha(source):
            if relative==Path('ppa.json'):
                shutil.copy2(source,dest)
            else:raise RuntimeError('Archived evidence changed: '+str(dest))
        elif not dest.exists():shutil.copy2(source,dest)
    hardware=folder/'frozen/hardware.txt'
    if hardware.is_file():
        compressed=target/'frozen/hardware.txt.gz'
        if not compressed.exists():
            with hardware.open('rb') as source,gzip.open(compressed,'wb',compresslevel=6) as dest:
                shutil.copyfileobj(source,dest)
        with gzip.open(compressed,'rb') as source:
            digest=hashlib.sha256()
            for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
        if digest.hexdigest()!=sha(hardware):
            raise RuntimeError('Archived hardware structure changed')
    write(target/'evidence_sha256.json',{
        str(p.relative_to(target)):sha(p) for p in sorted(target.rglob('*'))
        if p.is_file() and p.name!='evidence_sha256.json'})

def finalize(args):
    """Accept a routed candidate only after three INIT-only checkpoints exist."""
    tag=args.tag;folder=BUILD/tag
    result=json.loads((folder/'ppa.json').read_text())
    if result['stage']!='post_route':raise RuntimeError('Not a routed candidate')
    if 'frozen_hardware_sha256' in result:
        archive(tag)
        print('SLH_ONLY_ALREADY_FINALIZED',tag)
        return
    inputs=json.loads((folder/'inputs.json').read_text())
    validation={}
    validation_roots=set()
    if 'baseline' in inputs:
        identity=inputs['logic_sha256'];lid=logic_id(identity)
        for suite in ('unit','architecture','faults'):
            path=ACTIVE/suite/lid/'results.json'
            record=json.loads(path.read_text())
            if not record.get('passed') or record['logic_sha256']!=identity:
                raise RuntimeError('Missing functional acceptance: '+suite)
            validation_roots.add(path.parent)
        modes=[(0,False),(0,True)]
        if inputs['lanes']>1:modes.append((1,False))
        for swap,replay in modes:
            simdir=ACTIVE/'simulations'/lid/f'u{inputs["unroll"]}_l{inputs["lanes"]}_s{swap}'
            if replay:simdir=simdir/'replay'
            for name in SLH_PROFILES:
                path=simdir/(name+'.json');record=json.loads(path.read_text())
                if (not record.get('passed') or record['logic_sha256']!=identity
                        or record['lanes']!=inputs['lanes'] or record['unroll']!=inputs['unroll']
                        or record['swap']!=swap or record['reset_replay']!=replay
                        or record['log_sha256']!=sha(path.with_suffix('.log'))):
                    raise RuntimeError('Missing simulation acceptance: '+str(path))
                validation_roots.add(path.parent)
    clock=json.loads((folder/'final_clock.json').read_text())
    if clock['wns_ns']<0.0999 or clock['whs_ns']<0:
        raise RuntimeError('Final timing margin failed')
    status=(folder/'route_status.rpt').read_text()
    def net_count(label):
        match=re.search(r'# of '+label+r'\.*\s*:\s*(\d+)\s*:',status)
        if not match:raise RuntimeError('Missing route status '+label)
        return int(match[1])
    if net_count('routable nets')!=net_count('fully routed nets') or net_count('nets with routing errors'):
        raise RuntimeError('Route incomplete')
    coverage=(folder/'check_timing.rpt').read_text()
    for item in ('no_clock','constant_clock','pulse_width_clock',
                 'unconstrained_internal_endpoints','multiple_clock','loops','latch_loops'):
        if not re.search(r'checking '+item+r' \(0\)',coverage):
            raise RuntimeError('Timing coverage failed: '+item)
    evidence=folder/'frozen/evidence.tsv'
    rows=dict(line.split('\t') for line in evidence.read_text().splitlines())
    if set(rows)!=set(SLH_PROFILES) or len(set(rows.values()))!=1:
        raise RuntimeError('Three INIT checkpoints differ in common hardware')
    init_mapping=json.loads((folder/'frozen/init/mapping.json').read_text())
    for name in SLH_PROFILES:
        if not (folder/'frozen'/(name+'.dcp')).is_file():
            raise RuntimeError('Missing frozen checkpoint '+name)
        actual=dict(line.split('\t') for line in
                    (folder/'frozen'/(name+'_init.tsv')).read_text().splitlines())
        expected=init_mapping[name]
        if set(actual)!=set(expected) or any(
                int(actual[cell].split("'h")[1],16)!=int(value.split("'h")[1],16)
                for cell,value in expected.items()):
            raise RuntimeError('Frozen INIT values do not match image mapping: '+name)
    # Freeze the validation logs alongside the checkpoint. Re-running a
    # current-workspace test must not invalidate an accepted past candidate.
    for source in sorted(validation_roots):
        target=folder/'verification'/source.relative_to(ACTIVE)
        shutil.copytree(source,target,dirs_exist_ok=True)
    for path in sorted((folder/'verification').rglob('*')):
        if path.is_file():validation[str(path.relative_to(folder))]=sha(path)
    result['frozen_hardware_sha256']=next(iter(rows.values()))
    result['frozen_init_mapping_pass']=True
    if validation:result['functional_evidence_sha256']=validation
    result['performance_pass']=bool(result['numerical_pass'])
    write(folder/'ppa.json',result)
    archive(tag)
    print('SLH_ONLY_FINALIZED',tag,'performance_pass='+str(result['performance_pass']))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['sim','capture','collect','prepare_route','archive','finalize']);parser.add_argument('--tag',default='slh_only_l2_c0');parser.add_argument('--baseline',default='slh_only_l2_c2_route');parser.add_argument('--lanes',type=int,default=2,choices=[1,2,4]);parser.add_argument('--unroll',type=int,default=2,choices=[2]);parser.add_argument('--swap',type=int,default=0,choices=[0,1]);parser.add_argument('--profile',default='all',choices=['all',*SLH_PROFILES]);parser.add_argument('--jobs',type=int,default=8);parser.add_argument('--boundaries',action='store_true');parser.add_argument('--message-cases',action='store_true');parser.add_argument('--replay',action='store_true');parser.add_argument('--route',action='store_true');args=parser.parse_args();globals()[args.action](args) if args.action!='archive' else archive(args.tag)
