#!/usr/bin/env python3
"""Audit seven routed results from archived reports, snapshots and simulations."""
import csv,hashlib,json,math,re,sys,tarfile
from verify_rtl_matrix import matrix
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model.profiles import PROFILES
OUT=ROOT/'manifests/experiments/unified_hbs_v4'

def sha(data):return hashlib.sha256(data).hexdigest()
def check(condition,message):
    if not condition:raise AssertionError(message)
def equal(a,b,label):check(math.isclose(float(a),float(b),rel_tol=1e-11,abs_tol=1e-9),f'{label}: {a} != {b}')
def amount(text,label):
    m=re.search(r'^\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d,.]+)\s*\|',text,re.M)
    check(m is not None,f'missing resource {label}')
    return float(m[1].replace(',',''))

def main():
    final=json.loads((OUT/'final.json').read_text())
    check(set(final['profiles'])==set(PROFILES),'seven profiles required')
    versions=json.loads((OUT/'tool_versions.json').read_text())
    for key,value in [('iverilog','Icarus Verilog version 12.0'),('verilator','Verilator 5.008'),('vivado','Vivado v2025.2')]:check(value.lower() in versions[key].lower(),key+' tool version')
    check(sha((OUT/'verification.json').read_bytes())==final['verification_sha256'],'verification digest')
    verification=json.loads((OUT/'verification.json').read_text())
    check(sha((OUT/'icarus_units.log').read_bytes())==verification['unit_log_sha256'],'unit log digest')
    check(verification['unit_rtl_sha256']==final['rtl_sha256'],'unit RTL binding')
    for path,digest in verification['unit_sources'].items():check(sha((OUT/'verification_sources'/path).read_bytes())==digest,'unit source '+path)
    unit=(OUT/'icarus_units.log').read_text()
    for i in (3,4,5,6):check(f'UNIFIED_ADMISSION_PASS profile={i}' in unit,f'admission {i}')
    seen=set()
    for marker in ['VALUE_STORE_133_PASS','UNIFIED_ADMISSION_PASS','STATEFUL_INDEX_GUARD_PASS','COMPACT_SHAKE_CONTEXT_LANE_PASS']:
        check(marker in unit,marker)
    for i in range(7):check(f'UNIFIED_RECIPE_PASS profile={i} ' in unit,f'recipe {i}')
    for rel in verification['simulations']:
        path=OUT/rel;sim=json.loads(path.read_text());log=path.with_suffix('.log').read_bytes()
        check(sim['passed'] and sha(log)==sim['log_sha256'],f'simulation {rel}')
        check({k:v for k,v in sim['logic_sha256'].items() if k.endswith('.sv')}==final['rtl_sha256'],f'common RTL {rel}')
        check('Verilator 5.008' in sim['tool'],f'Verilator version {rel}')
        swap,bp=map(int,re.search(rb'swap=(\d+) backpressure=(\d+)',log).groups())
        if sim['unroll']==2:seen.add((sim['profile'],sim['lanes'],swap,bp,sim['q']))
    check(set(matrix())<=seen,'incomplete verification matrix')
    tables=json.loads((ROOT.parents[2]/'references/papers/Unified_HBS_Architecture_2026_Reader/data/paper_tables.json').read_text())['tables']
    old=json.loads((ROOT/'manifests/experiments/unified_hbs_final.json').read_text())['profiles']
    regression={'slh_128f':old['slh']['sign_atp'],'xmss_omega4':old['xmss']['sign_atp'],'lms_omega4':old['lms']['sign_atp']}
    rows=[];report=(ROOT/'docs/Unified_HBS_Paper_Comparison.md').read_text()
    for name,p in PROFILES.items():
        d=final['profiles'][name];directory=OUT/d['archive'];inp=json.loads((directory/'inputs.json').read_text())
        raw=json.loads((directory/'ppa.json').read_text())
        check(all(d[k]==v for k,v in raw.items()),name+' manifest vs PPA')
        snapshot=directory/'source_snapshot.tar.gz'
        check(sha(snapshot.read_bytes())==inp['snapshot_sha256'],name+' snapshot digest')
        check(sha(json.dumps(inp['source_sha256'],sort_keys=True).encode())==inp['source_set_sha256'],name+' source set')
        with tarfile.open(snapshot,'r:gz') as tar:
            for path,digest in inp['source_sha256'].items():check(sha(tar.extractfile(path).read())==digest,name+' source '+path)
            gate=json.load(tar.extractfile('manifests/experiments/unified_hbs_v4/software_gate.json'))
            check(gate['pass'],name+' software gate')
            for path,digest in gate['sources'].items():check(sha(tar.extractfile(path).read())==digest,name+' gate source '+path)
            models=json.load(tar.extractfile('manifests/experiments/unified_hbs_v4/model_gate.json'))
            for kind in ('keygen','sign'):
                data=bytes(int(x,16) for x in tar.extractfile(f'tb/vectors/uhbs_{name}_{kind}.mem').read().split())
                check(sha(data)==models['profiles'][name][kind+'_sha256'],name+' '+kind+' vector')
            route=json.loads((directory/'route_inputs.json').read_text())
            check(sha(tar.extractfile('experiments/route_unified_hbs.tcl').read())==route['script_sha256'],name+' route flow')
            clock=json.loads((directory/'final_clock.json').read_text())
            check(sha(tar.extractfile('experiments/finalize_unified_clock.tcl').read())==clock['script_sha256'],name+' clock flow')
        sim_path=OUT/'simulations'/(d['simulation']+'.json');sim=json.loads(sim_path.read_text())
        check(sha(sim_path.read_bytes())==d['simulation_sha256'],name+' simulation metadata')
        check(sim['logic_sha256']==inp['logic_sha256'],name+' synthesis/simulation binding')
        check(sim['unroll']==d['unroll'] and sim['lanes']==d['lanes'],name+' topology')
        sim_log=sim_path.with_suffix('.log').read_text();wait_cycles=int(re.search(r'RESIDENCY sign state=22 cycles=(\d+)',sim_log)[1])
        kg,sg=sim['keygen_cycles'],sim['sign_cycles'];equal(kg,d['keygen_cycles'],name+' KG cycles');equal(sg,d['sign_cycles'],name+' Sign cycles')
        util=(directory/'utilization.rpt').read_text()
        lut,ff,bram,dsp=[amount(util,x) for x in ('Slice LUTs','Slice Registers','Block RAM Tile','DSPs')]
        for key,value in [('lut',lut),('ff',ff),('bram36_equivalent',bram),('dsp',dsp)]:equal(d[key],value,name+' '+key)
        area=lut/4+ff/8+bram*232.4+dsp*102.4;period=clock['period_ns']
        equal(d['equivalent_slice'],area,name+' area');equal(d['period_ns'],period,name+' period')
        timing=(directory/'timing_summary.rpt').read_text()
        fields=re.search(r'WNS\(ns\).*?\n\s*[- ]+\n([^\n]+)',timing,re.S)[1].split()
        for key,index in [('wns_ns',0),('tns_ns',1),('whs_ns',4),('ths_ns',5),('wpws_ns',8),('tpws_ns',9)]:
            equal(d[key],fields[index],name+' '+key);check(float(fields[index])>=0,name+' timing '+key)
        check(d['wns_ns']>=0.0999,name+' setup margin')
        for key in ('tns_ns','ths_ns','tpws_ns'):equal(d[key],0,name+' '+key)
        equal(re.search(r'^clk\s+\{[^}]+\}\s+([\d.]+)',timing,re.M)[1],period,name+' report clock')
        coverage=(directory/'check_timing.rpt').read_text()
        for key in d['timing_coverage']:
            check(int(re.search(r'checking\s+'+key+r'\s+\((\d+)\)',coverage)[1])==0,name+' coverage '+key)
        status=(directory/'route_status.rpt').read_text()
        counts={k:int(re.search(re.escape(k)+r'[^\d\n]*?(\d+)',status,re.I)[1]) for k in d['route_counts']}
        check(counts['nets with routing errors']==0 and counts['routable nets']==counts['fully routed nets'],name+' routing')
        kg_ms,sg_ms=kg*period/1e6,sg*period/1e6;atp=area*sg_ms
        equal(atp,d['sign_atp'],name+' ATP');check(atp<p.target,name+' paper threshold')
        if name in regression:check(atp<=regression[name],name+' historical regression')
        scheme='SPHINCS+' if p.family=='slh' else p.family.upper()
        parameter=f'n={p.n*8}' if p.family=='slh' else f'h=10;omega={p.omega}'
        paper=next(r for r in tables['table5']['rows'] if r[0]==scheme and r[1]==parameter)
        resource=next(r for r in tables['table7']['rows'] if r[0]==scheme and r[1]=='This work' and r[2].replace('w=','omega=')==parameter)
        paper_area=resource[3]/4+resource[4]/8+resource[5]*232.4+resource[6]*102.4
        equal(round(paper_area*paper[5],3),p.target,name+' paper source')
        row=dict(profile=name,message_bytes=models['profiles'][name]['message_bytes'],sign_bytes=models['profiles'][name]['sign_bytes'],sign_hashes=models['profiles'][name]['sign_hashes'],sign_permutations=models['profiles'][name]['sign_permutations'],sign_hash_wait_cycles=wait_cycles,unroll=d['unroll'],lanes=d['lanes'],lut=int(lut),ff=int(ff),lutram=int(amount(util,"LUT as Memory")),bram36=bram,dsp=int(dsp),equivalent_slice=area,keygen_cycles=kg,sign_cycles=sg,frequency_mhz=1000/period,keygen_ms=kg_ms,sign_ms=sg_ms,keygen_atp=area*kg_ms,sign_atp=atp,paper_keygen_cycles=paper[2],paper_sign_cycles=paper[4],paper_keygen_ms=paper[3],paper_sign_ms=paper[5],paper_eq_slice=paper_area,paper_sign_atp=paper_area*paper[5],paper_keygen_atp=paper_area*paper[3],paper_keygen_ms_at_108mhz=paper[2]/108000,paper_sign_ms_at_108mhz=paper[4]/108000,paper_sign_atp_at_108mhz=paper_area*paper[4]/108000,lifecycle_atp=area*(kg+sg+4)*period/1e6,comparison='NON_STRICT',target_pass=True,regression_pass=True)
        for value in (f'{atp:,.3f}',f'{sg:,}',f'{kg:,}'):check(value in report,name+' report '+value)
        rows.append(row)
        print(f'{name:14} area={area:9.3f} KG={kg:10,} Sign={sg:9,} MHz={1000/period:7.3f} ATP={atp:11,.3f} target={p.target:11,.3f} PASS')
    expected=dict(schema='uhbs.seven_comparison.v4',final_sha256=sha((OUT/'final.json').read_bytes()),rows=rows)
    if '--write-comparison' in sys.argv:
        (OUT/'comparison.json').write_text(json.dumps(expected,indent=2)+'\n')
        with (OUT/'comparison.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    else:
        check(json.loads((OUT/'comparison.json').read_text())==expected,'comparison data mismatch')
        with (OUT/'comparison.csv').open(newline='') as stream:
            csv_rows=list(csv.DictReader(stream))
        check(len(csv_rows)==7,'CSV rows')
        for wanted,actual in zip(rows,csv_rows):
            for key,value in wanted.items():
                if isinstance(value,(int,float)) and not isinstance(value,bool):equal(actual[key],value,key)
                else:check(actual[key]==str(value),key+' CSV')
    if '--write-comparison' in sys.argv:
        report_path=ROOT/'docs/Unified_HBS_Paper_Comparison.md'
        text=report_path.read_text()
        begin='<!-- SEVEN_PROFILE_TIMES_BEGIN -->';end='<!-- SEVEN_PROFILE_TIMES_END -->'
        if begin in text:text=text.split(begin)[0]+text.split(end,1)[1]
        section=begin+'\n## 七点 Keygen、Sign 与论文计时口径\n\n'
        section+='| Profile | Keygen ms | Keygen ATP | Sign ms | 论文 Keygen ms | 论文 Keygen ATP | 论文 Sign ms | Sign ATP 降幅 |\n'
        section+='|---|---:|---:|---:|---:|---:|---:|---:|\n'
        for r in rows:
            section+=f'| {r["profile"]} | {r["keygen_ms"]:.6f} | {r["keygen_atp"]:,.3f} | {r["sign_ms"]:.6f} | {r["paper_keygen_ms"]:.2f} | {r["paper_keygen_atp"]:,.3f} | {r["paper_sign_ms"]:.2f} | {100*(1-r["sign_atp"]/r["paper_sign_atp"]):.2f}% |\n'
        section+='\n论文表 5 的毫秒值是报告值，和表中周期按 108 MHz 相除的结果有差异。下表单独列出重算口径；验收门槛仍使用上表报告值。\n\n'
        section+='| Profile | 论文 Keygen cycles | 论文 Sign cycles | Keygen ms @108 MHz | Sign ms @108 MHz | Sign ATP @108 MHz |\n|---|---:|---:|---:|---:|---:|\n'
        for r in rows:
            section+=f'| {r["profile"]} | {r["paper_keygen_cycles"]:,} | {r["paper_sign_cycles"]:,} | {r["paper_keygen_ms_at_108mhz"]:.6f} | {r["paper_sign_ms_at_108mhz"]:.6f} | {r["paper_sign_atp_at_108mhz"]:,.3f} |\n'
        section+='\n有状态四点在 Keygen 遍历完整 h=10 树时缓存指定 q 的十个认证节点和根，Sign 不再构树。缓存仅服务该次签名；下一次 start 会为下一个索引重算树。因此 Sign ATP 改善不能直接外推为多次签名吞吐率，Keygen+Sign 的生命周期 ATP 已单列在 CSV 中。索引持久化确认的外部延迟在基准中取零等待，实际等待会增加 Sign 周期。\n'
        section+='\n### 输入、工作量与优化证据\n\n| Profile | 消息字节 | 签名字节 | Sign Hash | Keccak 置换 | HASH_WAIT 占 Sign 周期 | LUTRAM（已含于 LUT） |\n|---|---:|---:|---:|---:|---:|---:|\n'
        for r in rows:
            section+=f'| {r["profile"]} | {r["message_bytes"]} | {r["sign_bytes"]:,} | {r["sign_hashes"]:,} | {r["sign_permutations"]:,} | {100*r["sign_hash_wait_cycles"]/r["sign_cycles"]:.2f}% | {r["lutram"]:,} |\n'
        section+='\n当前采用 U2、SLH 双 lane、有状态单 lane。候选 A→B→D 依次验证静态配方裁剪、直接结果输出、FORS 相邻叶并行，以及吸收输入流水和静态前缀选择。192f 的常量长度乘法曾映射为 6 个 DSP，禁止 DSP 推断后面积与时序均改善。U1 对照显示减少 Keccak 展开并未消除旧版输入选择路径瓶颈，故保留 U2。详细资源层次、候选关键路径和状态驻留日志随 [筛选表](../manifests/experiments/unified_hbs_v4/screening.csv) 归档。\n\n256f 的签名 ATP 接近门槛；周期与 setup 裕量可在 `final.json` 中核对。修改 RTL、工具或实现设置后须重新验收，不能直接沿用归档数值。\n'
        section+=end+'\n\n' 
        marker='## 历史 ABI 3'
        text=text.replace(marker,section+marker,1)
        report_path.write_text(text)
    print('Seven profiles, common RTL, independent software gates, verification and routed ATP: PASS')

if __name__=='__main__':main()
