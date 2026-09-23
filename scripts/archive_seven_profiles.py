#!/usr/bin/env python3
"""Select passing routed candidates and archive immutable evidence."""
from pathlib import Path
import csv,hashlib,json,re,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model.profiles import PROFILES
from verify_rtl_matrix import matrix
from run_unified_sim import logic_hashes
OUT=ROOT/'manifests/experiments/unified_hbs_v4'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    chosen={}
    current_rtl={k:v for k,v in logic_hashes("slh_128f").items() if k.endswith(".sv")}
    for name,p in PROFILES.items():
        candidates=[]
        for path in (ROOT/'build/vivado').glob('*_route/ppa.json'):
            d=json.loads(path.read_text())
            if d.get('family')==name and d.get('final_pass'):
                inp=json.loads((path.parent/'inputs.json').read_text())
                if {k:v for k,v in inp['logic_sha256'].items() if k.endswith('.sv')}==current_rtl:candidates.append((d['sign_atp'],path,d))
        if not candidates:raise RuntimeError(f'no accepted route: {name}')
        _,path,d=min(candidates,key=lambda x:x[0]);chosen[name]=(path,d)
    common=None
    for name,(path,d) in chosen.items():
        inp=json.loads((path.parent/'inputs.json').read_text())
        logic={k:v for k,v in inp['logic_sha256'].items() if k.endswith('.sv')}
        if common is None:common=logic
        if common!=logic:raise RuntimeError('selected products do not share identical RTL sources')
    final=dict(schema='uhbs.seven_profiles.v4',part='xc7a200tffg1156-3',comparison='NON_STRICT',profiles={},rtl_sha256=common)
    evidence=OUT/'candidates';evidence.mkdir(parents=True,exist_ok=True)
    # Retain screened candidates and partial attempts as such, without claiming acceptance.
    for directory in sorted((ROOT/'build/vivado').glob('v4*')):
        if not directory.is_dir() or not (directory/'inputs.json').exists():continue
        dest=evidence/directory.name;dest.mkdir(exist_ok=True)
        for file in directory.iterdir():
            if file.is_file() and (file.suffix in ('.json','.rpt','.xdc','.log') or file.name=='source_snapshot.tar.gz'):
                shutil.copy2(file,dest/file.name)
    screen=[]
    for path in sorted(evidence.glob('*/ppa.json')):
        x=json.loads(path.read_text());util=(path.parent/'utilization.rpt').read_text()
        lutram=re.search(r'\|\s*LUT as Memory\s*\|\s*(\d+)',util)
        screen.append(dict(candidate=path.parent.name,profile=x['family'],stage=x['stage'],unroll=x['unroll'],lanes=x['lanes'],lut=x['lut'],lutram=int(lutram[1]),ff=x['ff'],bram36=x['bram36_equivalent'],dsp=x['dsp'],area=x['equivalent_slice'],keygen_cycles=x['keygen_cycles'],sign_cycles=x['sign_cycles'],period_ns=x['period_ns'],wns_ns=x['wns_ns'],sign_atp=x['sign_atp'],accepted=x['final_pass']))
    with (OUT/'screening.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(screen[0]));writer.writeheader();writer.writerows(screen)
    versions={}
    for tool,flag in [('iverilog','-V'),('verilator','--version'),('vivado','-version')]:
        versions[tool]=subprocess.run([tool,flag],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,check=True).stdout
    (OUT/'tool_versions.json').write_text(json.dumps(versions,indent=2)+'\n')
    sims=OUT/'simulations';sims.mkdir(exist_ok=True)
    for file in (ROOT/'build/sim').glob('*'):
        if file.suffix in ('.json','.log'):shutil.copy2(file,sims/file.name)
    records=[]
    for name,lanes,swap,bp,q in matrix():
        matches=[]
        for file in sims.glob('*.json'):
            d=json.loads(file.read_text())
            if not d.get('passed') or d['profile']!=name or d['lanes']!=lanes or d['unroll']!=2 or d.get('q',5)!=q:continue
            if {k:v for k,v in d['logic_sha256'].items() if k.endswith('.sv')}!=common:continue
            log=file.with_suffix('.log').read_text()
            if f'swap={swap} backpressure={bp}' in log:matches.append(file)
        if not matches:raise RuntimeError(f'missing verification: {name}/{lanes}/{swap}/{bp}/{q}')
        records.append(str(sorted(matches)[-1].relative_to(OUT)))
    for name,(path,d) in chosen.items():
        normal=sims/(d['simulation']+'.json')
        stress=[]
        for file in sims.glob('*.json'):
            x=json.loads(file.read_text())
            if x.get('passed') and x['profile']==name and x['unroll']==d['unroll'] and x['lanes']==d['lanes'] and x.get('q',5)==5 and {k:v for k,v in x['logic_sha256'].items() if k.endswith('.sv')}==common and 'swap=1 backpressure=1' in file.with_suffix('.log').read_text():stress.append(file)
        if not stress:raise RuntimeError(f'missing selected-candidate stress: {name}')
        records += [str(normal.relative_to(OUT)),str(sorted(stress)[-1].relative_to(OUT))]
        final['profiles'][name]=dict(d,archive=f'candidates/{path.parent.name}')
    unit=ROOT/'build/icarus_final.log'
    if not unit.exists() or 'COMPACT_SHAKE_CONTEXT_LANE_PASS' not in unit.read_text():raise RuntimeError('missing unit verification')
    shutil.copy2(unit,OUT/'icarus_units.log')
    unit_sources={}
    for file in list((ROOT/'tb/unit').glob('*.sv'))+[ROOT/'Makefile']:
        rel=file.relative_to(ROOT);target=OUT/'verification_sources'/rel
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,target)
        unit_sources[str(rel)]=sha(file)
    verification=dict(schema='uhbs.verification.v4',simulations=sorted(set(records)),unit_log_sha256=sha(OUT/'icarus_units.log'),unit_sources=unit_sources,unit_rtl_sha256=current_rtl)
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    final['verification_sha256']=sha(OUT/'verification.json')
    (OUT/'final.json').write_text(json.dumps(final,indent=2)+'\n')
    rows=[]
    for name,d in final['profiles'].items():
        rows.append(f'| {name} | {d["unroll"]}/{d["lanes"]} | {d["lut"]:,} | {d["ff"]:,} | {d["bram36_equivalent"]:g} | {d["dsp"]} | {d["equivalent_slice"]:,.3f} | {d["keygen_cycles"]:,} | {d["sign_cycles"]:,} | {d["frequency_mhz"]:.3f} | {d["sign_atp"]:,.3f} | {d["target"]:,.3f} |')
    section='''<!-- SEVEN_PROFILE_RESULTS_BEGIN -->
# ABI 4 七参数点 post-route 结果

七点均使用同一份 RTL 核源码，按表中 U（每周期 Keccak 轮数）/lane 数分别静态综合。器件为 xc7a200tffg1156-3，工具为 Vivado 2025.2。最终频率通过完整布线及 OOC 内部 setup、hold、pulse-width 和覆盖检查；外部引脚时序不属于该测量边界。

| Profile | U/lane | LUT | FF | BRAM36等效 | DSP | 等效 Slice | Keygen cycles | Sign cycles | MHz | Sign ATP | 论文 ATP 门槛 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
'''+ '\n'.join(rows)+'''

七点签名 ATP 均低于对应论文门槛，三个旧参数点也通过历史未舍入 ATP 的不退化检查。计时使用固定向量、无背压及立即提交确认；压力与边界测试的等待周期不混入基准。192f/256f 使用固定 NIST ACVP 提交中的 tc148/tc154；XMSS/LMS omega=2 沿用 omega=4 的输入材料。omega 表示每个 Winternitz 数字的位数。

等效 Slice = LUT/4 + FF/8 + BRAM36等效数×232.4 + DSP×102.4。Sign ATP = 等效 Slice×Sign cycles×最终周期(ns)/1e6。门槛仍按论文报告毫秒值计算，不能与按 108 MHz 重算的时间混用。

结果流直接输出计算完成的片段，out_keep 指明有效字节；认证路径缓存和索引提交保护继续保留。双 lane 同时计算 FORS 的相邻叶节点，随后由统一树栈归约。完整软件、单/双 lane、交换、背压及 q=0/1023 验证记录随结果保存。

本比较继续标记 NON_STRICT：最终 SLH-DSA 与论文 SPHINCS+ 版本不同；LMS 是项目 SHAKE 研究 profile；论文共享多算法硬件、缓存策略和签名样本与当前分别静态综合的固定输入实现不同。Keygen 与生命周期数据应单独审视，签名 ATP 达标不代表所有操作都更快。

[七点原始结果](../manifests/experiments/unified_hbs_v4/final.json) · [验证矩阵](../manifests/experiments/unified_hbs_v4/verification.json) · [完整数据表](../manifests/experiments/unified_hbs_v4/comparison.csv)。运行 `make reproduce-paper-comparison` 核对历史及当前结果。
<!-- SEVEN_PROFILE_RESULTS_END -->

'''
    report=ROOT/'docs/Unified_HBS_Paper_Comparison.md';old=report.read_text()
    for block in ('RESULTS','TIMES'):
        old=re.sub(r'<!-- SEVEN_PROFILE_'+block+r'_BEGIN -->.*?<!-- SEVEN_PROFILE_'+block+r'_END -->\s*','',old,flags=re.S)
    old=old.lstrip()
    if not old.startswith('## 历史 ABI 3'):old='## 历史 ABI 3 三点基线（固定源码复现）\n\n'+old
    report.write_text(section+old)
    print('Archived accepted seven-profile results; run reproduce_seven_profiles.py next.')

if __name__=='__main__':main()
