#!/usr/bin/env python3
"""Audit v4.1 archived evidence; refuse to turn partial PPA into acceptance."""
from pathlib import Path
import argparse,gzip,hashlib,json,math,re,sys,tarfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model.profiles import PROFILES
from model.autonomous_hbs import ProgramImage
from rom_initialization import mapping
BASE=ROOT/'manifests/experiments/unified_hbs_v4.1'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def archived_source_sha(path):
    snapshot=BASE/'candidates/u2_area_balanced_route/source_snapshot.tar.gz'
    with tarfile.open(snapshot,'r:gz') as tar:
        source=tar.extractfile(path)
        check(source is not None,'historical source missing '+path)
        return hashlib.sha256(source.read()).hexdigest()
def hardware_sha(folder):
    path=folder/'hardware.txt'
    if path.exists():return sha(path)
    digest=hashlib.sha256()
    with gzip.open(folder/'hardware.txt.gz','rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()
def check(ok,message):
    if not ok:raise AssertionError(message)
def eq(a,b):return math.isclose(float(a),float(b),rel_tol=1e-11,abs_tol=1e-9)
def audit_area_software():
    folder=BASE/'software/area_v1'
    if not folder.exists():return
    from model.physical_image import PhysicalImage,validate_serial_schedule
    gate=json.loads((folder/'software_gate.json').read_text())
    check(gate['passed'] and set(gate['profiles'])==set(PROFILES),'area software coverage')
    for name,digest in gate['source_sha256'].items():check(archived_source_sha(name)==digest,'area software source '+name)
    expected={'template_lane1','template_coordinate','physical_reserved','physical_capacity',
              'descriptor_width','unmapped_descriptor','nonzero_event','initial_wait'}
    check(set(gate['rejected'])==expected,'area software error coverage')
    for name,row in gate['profiles'].items():
        logical=ProgramImage.read(BASE/'images'/name)
        check(PhysicalImage.read(folder/'images'/name).unpack()==logical,'physical round trip '+name)
        validate_serial_schedule(logical)
        for kind,directory in [('logical',BASE/'images'/name),('physical',folder/'images'/name)]:
            for file,digest in row[kind+'_sha256'].items():check(sha(directory/file)==digest,'area image '+name+'/'+file)
        meta=[int(x,16) for x in (BASE/'images'/name/'metadata.mem').read_text().split()]
        check([*row['stats']['keygen'],*row['stats']['sign']]==meta[2:6],'area software counts '+name)
        for phase in ('keygen','sign'):
            expected_bytes=bytes(int(x,16) for x in (BASE/'images'/name/(phase+'.mem')).read_text().split())
            check(hashlib.sha256(expected_bytes).hexdigest()==row[phase+'_sha256'],'area software output '+name)
    print('V4.1 compact-image/single-macro software gate: PASS')
    reference=json.loads((BASE/'area_baseline.json').read_text())
    baseline=BASE/'candidates'/reference['candidate']/'ppa.json'
    check(sha(baseline)==reference['ppa_sha256'],'area baseline source')
    measured=json.loads(baseline.read_text())
    for field in ('stage','equivalent_slice','frequency_mhz'):check(reference[field]==measured[field],'area baseline '+field)
    check(reference['max_sign_cycle_increase_percent']==5,'area cycle budget')
    for name,cycles in reference['profiles'].items():
        for field,value in cycles.items():check(measured['profiles'][name][field]==value,'area baseline cycles '+name)
    for name in ('packed_roms','area_lanes','freeze_query_failed','incremental_placement','stream32_relaxed_incomplete','stream32_route_incomplete'):
        directory=BASE/'screening'/name
        records=json.loads((directory/'evidence.json').read_text())
        for file,digest in records.get('evidence_sha256',records).items():
            check(sha(directory/file)==digest,'local synthesis evidence '+name+'/'+file)
    selection=BASE/'area_selection.json'
    if selection.exists():
        data=json.loads(selection.read_text())
        check(data['baseline']==reference['candidate'] and data['baseline_sha256']==sha(baseline),'selection baseline')
        eligible=[]
        for tag,row in data['candidates'].items():
            path=BASE/'candidates'/tag/'ppa.json';ppa=json.loads(path.read_text())
            check(sha(path)==row['ppa_sha256'],'selection candidate '+tag)
            cycle_ok=all(p['sign_cycles']*100<=reference['profiles'][n]['sign_cycles']*105 for n,p in ppa['profiles'].items())
            area_ok=ppa['equivalent_slice']<measured['equivalent_slice']
            atp_ok=ppa['worst_ratio']<measured['worst_ratio']
            check(row['cycle_limit_pass']==cycle_ok and row['area_improves']==area_ok and row['worst_atp_ratio_improves']==atp_ok,'selection predicates '+tag)
            check(row['eligible']==(cycle_ok and area_ok and atp_ok),'selection eligibility '+tag)
            if row['eligible']:
                check((path.parent/'frozen/evidence.tsv').exists(),'selected area candidate needs frozen proof')
                eligible.append((ppa['equivalent_slice'],ppa['worst_ratio'],tag))
        check(data['selected']==(min(eligible)[2] if eligible else reference['candidate']),'area candidate selection')
        print('V4.1 routed area/cycle/ATP selection: PASS',data['selected'])

def audit_frozen(folder,inputs):
    frozen=folder/'frozen'
    if not (frozen/'evidence.tsv').exists():return
    rows=dict(line.split('\t') for line in (frozen/'evidence.tsv').read_text().splitlines())
    check(set(rows)==set(PROFILES),'frozen profile coverage')
    check(set(rows.values())=={hardware_sha(frozen)},'identical frozen structure')
    with tarfile.open(folder/'source_snapshot.tar.gz') as tar:
        top=tar.extractfile('rtl/top/mhbs_top.sv').read().decode()
    packed=bool(re.search(r'\.PACKING\(1\)',top))
    identity=hashlib.sha256(json.dumps(inputs['logic_sha256'],sort_keys=True).encode()).hexdigest()[:16]
    boundary=BASE/'boundary'/identity
    if packed:
        evidence=json.loads((boundary/'evidence.json').read_text())
        check(evidence['passed'] and evidence['logic_sha256']==inputs['logic_sha256'],'ROM boundary source')
        for file,digest in evidence['evidence_sha256'].items():check(sha(boundary/file)==digest,'ROM boundary evidence '+file)
        check(sha(boundary/'structure_0.txt')==sha(boundary/'structure_1.txt'),'INIT-independent optimization')
    util=(folder/'utilization.rpt').read_text()
    for name in PROFILES:
        check((frozen/(name+'.dcp')).is_file(),'frozen checkpoint '+name)
        other=(frozen/(name+'_utilization.rpt')).read_text()
        check(all(resource(util,k)==resource(other,k) for k in ('Slice LUTs','Slice Registers','LUT as Memory','Block RAM Tile','DSPs')),'frozen resource equality '+name)
        expected=mapping(name)
        if not packed:
            expected={k:v for k,v in expected.items() if not k.startswith('template_rom/')}
            words=ProgramImage.read(BASE/'images'/name).templates
            for bit in range(128):
                column=sum(((word>>bit)&1)<<address for address,word in enumerate(words))
                expected[f'template_rom/port_bank[0].bit_cell[{bit}].depth64.rom']=f"64'h{column:016x}"
        actual=dict(line.split('\t') for line in (frozen/(name+'_init.tsv')).read_text().splitlines())
        check(set(actual)==set(expected),'frozen ROM cells '+name)
        check(all(int(actual[k].split("'h")[1],16)==int(v.split("'h")[1],16) for k,v in expected.items()),'frozen physical INIT '+name)
    print('V4.1 seven INIT images / common area, placement and routing: PASS',folder.name)
def resource(text,label):
    match=re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d,.]+)\s*\|',text)
    check(match is not None,'missing resource '+label)
    return float(match[1].replace(',',''))
def audit_physical(folder):
    clock=json.loads((folder/'final_clock.json').read_text())
    check(eq(clock['period_ns']*10,round(clock['period_ns']*10)) and clock['wns_ns']>=.0999 and clock['whs_ns']>=0,'physical clock margin')
    timing=(folder/'timing_summary.rpt').read_text()
    row=re.search(r'WNS\(ns\).*?\n\s*[- ]+\n([^\n]+)',timing).group(1).split()
    check(all(float(row[i])>=0 for i in (0,4,8)) and all(float(row[i])==0 for i in (1,5,9)),'physical setup/hold/pulse')
    route=(folder/'route_status.rpt').read_text()
    # Vivado 2025.2 omits the unrouted row when all routable nets are routed.
    def nets(label):
        m=re.search(r'# of '+re.escape(label)+r'\.*\s*:\s*(\d+)',route)
        check(m is not None,'missing route count '+label)
        return int(m[1])
    check(nets('nets with routing errors')==0,'routing errors')
    check(nets('routable nets')==nets('fully routed nets'),'incomplete routing')
    coverage=(folder/'check_timing.rpt').read_text()
    for label in ('no_clock','constant_clock','pulse_width_clock','multiple_clock','unconstrained_internal_endpoints','loops','latch_loops'):
        m=re.search(r'checking '+label+r' \((\d+)\)',coverage);check(m and int(m[1])==0,'coverage '+label)
    print('V4.1 routing/timing/coverage: PASS',folder.name)

def audit_architecture():
    for folder in sorted((BASE/'architecture').glob('*')):
        if not (folder/'results.json').exists():continue
        data=json.loads((folder/'results.json').read_text())
        gate=json.loads((folder/'model_gate.json').read_text())
        identity=hashlib.sha256(json.dumps(data['logic_sha256'],sort_keys=True).encode()).hexdigest()[:16]
        check(identity==folder.name and data['passed'] and gate['passed'],'architecture identity/gate')
        probes=data['probes']
        check(set(probes)=={'base','program','template','recipe','route','loop','run'},'architecture coverage')
        for name,probe in probes.items():
            check(probe['model_pass'] and probe['rtl_pass'],'architecture pass '+name)
            log=folder/(name+'.log');check(sha(log)==probe['log_sha256'],'architecture log '+name)
            for file,digest in probe['image_sha256'].items():
                check(sha(folder/'images'/name/file)==digest,'architecture image '+name+'/'+file)
            text=log.read_text()
            trace=[[int(phase),int(cmd,16)] for phase,cmd in re.findall(r'MACRO_TRACE phase=(\d+) command=([0-9a-f]+)',text)]
            check('AUTONOMOUS_PASS' in text and trace==probe['macro_trace'],'architecture trace '+name)
            check(all(probe[k]==v for k,v in gate['probes'][name].items()),'architecture software/RTL evidence '+name)
        check(probes['program']['macro_trace']!=probes['base']['macro_trace'],'program changes execution')
        check(probes['template']['macro_trace']!=probes['base']['macro_trace'],'template changes execution')
        check(probes['loop']['macro_trace']==probes['run']['macro_trace'],'loop/run expansion')
        for name in ('recipe','route'):
            check(probes[name]['oracle_sha256']!=probes['base']['oracle_sha256'],name+' changes output')
        print('V4.1 image-driven architecture: PASS',identity)

def audit_functional(inputs):
    logic=inputs['logic_sha256']
    identity=hashlib.sha256(json.dumps(logic,sort_keys=True).encode()).hexdigest()[:16]
    source=inputs['source_sha256'];bench=source['tb/integration/tb_mhbs_autonomous.sv']
    unit_folder=BASE/'unit'/identity
    unit=json.loads((unit_folder/'results.json').read_text())
    check(unit['pass_all'] and unit['logic_sha256']==logic and unit['bench_sha256']==bench,'functional units/source')
    for name,digest in unit['test_sha256'].items():check(source[name]==digest,'unit test source '+name)
    for name,digest in unit['logs'].items():check(sha(unit_folder/(name+'.log'))==digest,'unit log '+name)
    check('boot_drain' in unit['logs'],'boot pipeline drain coverage')
    sim_folder=BASE/'simulations'/identity
    names=list(PROFILES)+[name+f'_q{q}' for name,p in PROFILES.items() if p.stateful for q in (0,1023)]
    names+=list(json.loads((BASE/'message_cases.json').read_text()))
    normal_binaries=set()
    for variant,profiles,replay in [('u2_l2_s0',names,False),('u2_l2_s1',list(PROFILES),False),('u2_l2_s0/replay',list(PROFILES),True)]:
        binaries=set()
        for name in profiles:
            file=sim_folder/variant/(name+'.json');data=json.loads(file.read_text())
            check(data['passed'] and data['logic_sha256']==logic and data['bench_sha256']==bench,'functional simulation/source '+name)
            check(data['reset_replay']==replay and data['lanes']==2 and data['unroll']==2,'functional topology/replay')
            check(data['swap']==int(variant.startswith('u2_l2_s1')),'lane swap')
            check(sha(file.with_suffix('.log'))==data['log_sha256'],'functional simulation log '+name)
            for image,digest in data['image_sha256'].items():check(sha(BASE/'images'/name/image)==digest,'functional simulation image '+name)
            metadata=[int(x,16) for x in (BASE/'images'/name/'metadata.mem').read_text().split()]
            check([data[k] for k in ('keygen_hashes','keygen_permutations','sign_hashes','sign_permutations')]==metadata[2:6],'functional Hash/Keccak counts '+name)
            binaries.add(data['binary_sha256'])
        check(len(binaries)==1,'common simulation executable '+variant)
        if variant=='u2_l2_s0':normal_binaries=binaries
    faults_folder=BASE/'state_verification'/identity/'u2_l2_s0'
    faults=json.loads((faults_folder/'results.json').read_text())
    check(faults['pass_all'] and faults['logic_sha256']==logic and faults['bench_sha256']==bench,'fault source')
    check(faults['binary_sha256'] in normal_binaries,'fault executable')
    expected={name+f'_fault{i}.log' for name,p in PROFILES.items() if p.stateful for i in (1,2,3)}
    check(set(faults['logs'])==expected,'fault matrix coverage')
    for name,digest in faults['logs'].items():check(sha(faults_folder/name)==digest and 'AUTONOMOUS_FAULT_PASS' in (faults_folder/name).read_text(),'fault log '+name)
    arch=json.loads((BASE/'architecture'/identity/'results.json').read_text())
    check(arch['passed'] and arch['logic_sha256']==logic,'architecture source')
    for name,digest in arch['bench_sha256'].items():check(source[name]==digest,'architecture bench '+name)
    check(arch['script_sha256']==source['scripts/verify_microcode_architecture.py'],'architecture driver source')
    physical=json.loads((unit_folder/'physical_rom.json').read_text())
    check(physical['passed'] and physical['rom_rtl_sha256']==logic['rtl/memory/mhbs_image_rom.sv'],'physical ROM source')
    check(physical['generator_sha256']==source['scripts/verify_physical_rom.py'],'physical ROM test generator source')
    for name,images in physical['image_sha256'].items():
        for kind,digest in images.items():check(sha(BASE/'images'/name/(kind+'.mem'))==digest,'physical ROM image '+name+'/'+kind)
    check(sha(unit_folder/'physical_rom.log')==physical['log_sha256'],'physical ROM log')
    print('V4.1 complete functional evidence: PASS',identity)

def audit_candidates():
    ceilings_raw=json.loads((ROOT/'manifests/experiments/unified_hbs_final.json').read_text())['profiles']
    ceilings={a:ceilings_raw[b]['sign_atp'] for a,b in [('slh_128f','slh'),('xmss_omega4','xmss'),('lms_omega4','lms')]}
    for folder in sorted((BASE/'candidates').glob('*')):
        if not (folder/'evidence.json').exists():continue
        evidence=json.loads((folder/'evidence.json').read_text())
        for name,digest in evidence['evidence_sha256'].items():
            check(sha(folder/name)==digest,'candidate evidence '+folder.name+'/'+name)
        inputs=json.loads((folder/'inputs.json').read_text())
        ppa=json.loads((folder/'ppa.json').read_text())
        check(sha(folder/'inputs.json')==ppa['inputs_sha256'],'candidate inputs '+folder.name)
        check(sha(folder/'source_snapshot.tar.gz')==inputs['snapshot_sha256'],'candidate snapshot '+folder.name)
        with tarfile.open(folder/'source_snapshot.tar.gz') as tar:
            for name,digest in inputs['source_sha256'].items():
                check(hashlib.sha256(tar.extractfile(name).read()).hexdigest()==digest,'candidate source '+name)
        check(all(inputs['source_sha256'][name]==digest for name,digest in inputs['logic_sha256'].items()),'candidate logic closure')
        util=(folder/'utilization.rpt').read_text()
        area=resource(util,'Slice LUTs')/4+resource(util,'Slice Registers')/8+resource(util,'Block RAM Tile')*232.4+resource(util,'DSPs')*102.4
        check(eq(area,ppa['equivalent_slice']),'candidate area '+folder.name)
        period=10 if ppa['stage']=='post_synth' else json.loads((folder/'final_clock.json').read_text())['period_ns']
        if ppa['stage']=='post_route':audit_physical(folder)
        if ppa['stage']=='post_route':audit_frozen(folder,inputs)
        check(eq(period,ppa['period_ns']) and eq(1000/period,ppa['frequency_mhz']),'candidate frequency')
        ratios=[]
        for name,p in PROFILES.items():
            row=ppa['profiles'][name];path=ROOT/row['simulation'];sim=json.loads(path.read_text())
            check(sha(path)==row['simulation_sha256'] and sha(path.with_suffix('.log'))==sim['log_sha256'],'candidate simulation '+name)
            check(sim['passed'] and sim['logic_sha256']==inputs['logic_sha256'],'candidate cycle/source mismatch '+name)
            for kind in ('boot','keygen','sign'):
                check(row[kind+'_cycles']==sim[kind+'_cycles'],'candidate cycles '+name)
            atp=area*sim['sign_cycles']*period/1e6
            ratio=atp/min(p.target,ceilings.get(name,float('inf')))
            check(eq(atp,row['sign_atp']) and eq(ratio,row['ratio']),'candidate ATP '+name)
            check(eq(row['keygen_atp'],area*sim['keygen_cycles']*period/1e6),'candidate Keygen ATP '+name)
            check(row['paper_pass']==(atp<p.target) and row['v3_pass']==(name not in ceilings or atp<=ceilings[name]),'candidate pass flags '+name)
            if 'cycle_reference' in ppa:
                reference=json.loads((BASE/'area_baseline.json').read_text())
                check(sha(BASE/'area_baseline.json')==ppa['cycle_reference_sha256'],'cycle reference digest')
                check(reference['candidate']==ppa['cycle_reference'],'cycle reference candidate')
                before=reference['profiles'][name]['sign_cycles']
                check(eq(row['sign_cycle_ratio'],row['sign_cycles']/before),'cycle ratio '+name)
                check(row['cycle_limit_pass']==(row['sign_cycles']*100<=before*105),'5% cycle limit '+name)
            ratios.append(ratio)
        check(eq(max(ratios),ppa['worst_ratio']),'candidate ranking '+folder.name)
        if 'cycle_reference' in ppa:check(ppa['cycle_limit_pass']==all(r['cycle_limit_pass'] for r in ppa['profiles'].values()),'overall 5% cycle limit')
        print('V4.1 candidate audit: PASS',folder.name,ppa['stage'])

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--allow-incomplete',action='store_true');parser.add_argument('--functional-tag');args=parser.parse_args()
    gate=json.loads((BASE/'software_gate.json').read_text());check(gate['pass'],'software gate')
    for path,digest in gate['sources'].items():check(archived_source_sha(path)==digest,'software source '+path)
    images=json.loads((BASE/'images.json').read_text())['profiles']
    for name,data in images.items():
        folder=BASE/'images'/name;ProgramImage.read(folder).decode()
        for path,digest in data['image_sha256'].items():check(sha(folder/path)==digest,'ROM image '+name+'/'+path)
    print('V4.1 software gate / images: PASS')
    audit_area_software()
    update=json.loads((BASE/'author_update.json').read_text())
    check(update['updated_sign_cycles']==815706 and update['changes_acceptance_threshold'] is False,'author update/unchanged acceptance')
    audit_architecture()
    audit_candidates()
    if args.functional_tag:
        audit_functional(json.loads((BASE/'candidates'/args.functional_tag/'inputs.json').read_text()))
    final_path=BASE/'final.json'
    if not final_path.exists():
        print('V4.1 performance acceptance: INCOMPLETE (no final manifest)')
        return 0 if args.allow_incomplete else 2
    final=json.loads(final_path.read_text());check(final['version']=='v4.1' and final['abi_version']==4,'version/ABI')
    folder=BASE/final['archive'];inputs=json.loads((folder/'inputs.json').read_text());ppa=json.loads((folder/'ppa.json').read_text())
    audit_functional(inputs)
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
    audit_physical(folder)
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
    check(next(iter(structural))==hardware_sha(folder/'frozen'),'frozen structure digest')
    check(final['functional_pass'] and final['performance_pass'],'final acceptance flags')
    print('V4.1 seven-profile common-hardware acceptance: PASS')
    return 0
if __name__=='__main__':sys.exit(main())
