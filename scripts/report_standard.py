#!/usr/bin/env python3
"""Report measured migration results; completion fails closed on missing evidence."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model.profiles import PROFILES

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'docs/manifests/experiments/stateful_standard_20261013/reports/Stateful_SHAKE256_Standard_Migration_20261013'
ARCHIVE=ROOT/'docs/manifests/experiments/stateful_standard_20261013'

def utilization(path):
    if not path.exists():return None
    text=path.read_text();values={}
    for key,label in [('lut','Slice LUTs'),('ff','Slice Registers'),('bram36','Block RAM Tile'),('dsp','DSPs')]:
        match=re.search(r'^\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d.]+)',text,re.M)
        if not match:raise ValueError(f'{path}: missing {label}')
        values[key]=float(match.group(1))
    values['equivalent_slice']=values['lut']/4+values['ff']/8+232.4*values['bram36']+102.4*values['dsp']
    return values

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-complete',action='store_true')
    args=parser.parse_args()
    status_path=ROOT/'build/standard_migration/full36/status.json'
    status=json.loads(status_path.read_text()) if status_path.exists() else dict(passed=0,required=36,complete=False,errors=[],results=[])
    common=utilization(ROOT/'build/synth/P4U1_generic/core_utilization.rpt')
    stateful=[p for p in PROFILES.values() if p.stateful]
    tops={p.name:utilization(ROOT/'build/synth/top_P4U1_generic'/p.name/'top_utilization.rpt') for p in stateful}
    results={r['profile']+'/'+r['operation']:r for r in status['results']}
    retained_path=ROOT/'build/standard_migration/full30/status.json'
    retained=json.loads(retained_path.read_text()) if retained_path.exists() else None
    if status.get('stopped_by_user') and retained:
        results.update({r['profile']+'/'+r['operation']:r for r in retained['results']})
    def passed(path, marker):return path.exists() and marker in path.read_text(errors='replace')
    gates=dict(full36=status['complete'] and status['passed']==36 and not status['errors'] and passed(ROOT/'build/standard_migration/full36.log','STANDARD_FULL36_PASS'),
        recipes=passed(ROOT/'build/standard_recipe_boundaries.log','RECIPE_PASS cases=459'),
        tags=passed(ROOT/'build/standard_pipeline_boundaries.log','PIPELINE_PASS family=2'),
        models=passed(ROOT/'build/standard_models.log','STANDARD_MODEL_PASS'),
        common_synthesis=passed(ROOT/'build/standard_common_synth.log','MHBS_SYNTH_PASS'),
        top_synthesis=all(passed(ROOT/'build/synth/top_P4U1_generic'/p.name/'vivado.log',f'MHBS_TOP_SYNTH_PASS profile={p.name}') for p in stateful),
        edge_verify=all(passed(ROOT/f'build/standard_migration/edge_rtl/{p.name}_q{q}_verify.log','STATEFUL_PASS') for p in stateful for q in [1,(1<<p.h)-1]),
        edge_reject=all(passed(ROOT/f'build/standard_migration/edge_rtl/{p.name}_rejectq{q}.log','INDEX_REJECT_PASS') for p in stateful for q in [1<<p.h,0xffffffff]),
        compatibility=all(passed(ROOT/f'build/standard_smoke_P{p}U{u}.log',f'STATEFUL_PASS P{p}U{u} op=1') for p,u in [(1,2),(4,2),(12,1)]),
        single_slot_tail=passed(ROOT/'build/standard_tail_P6U1.log','STATEFUL_PASS P6U1'),
        stats0=passed(ROOT/'build/standard_stats0_lms.log','STATEFUL_PASS P4U1'),
        replay=passed(ROOT/'build/standard_stalls_xmss.log','STATEFUL_PASS P4U1'),
        qmax_sign=passed(ROOT/'build/standard_q1023_sign.log','STATEFUL_PASS P4U1'),
        q1_sign=passed(ROOT/'build/standard_q1_sign.log','STATEFUL_PASS P4U1'))
    if status.get('stopped_by_user'):
        gates['retained_full30']=bool(retained and retained['complete'] and retained['passed']==30 and not retained['errors'] and passed(ROOT/'build/standard_migration/full30.log','STANDARD_FULL30_PASS'))
    for name in ['slh_128f','xmss_h10','lms_h10']:
        gates[name+'_fault_cut_tamper']=all(passed(ROOT/f'build/standard_migration/extended/{name}_{label}.log',marker)
            for label,marker in [*[(f'tamper{i}','STATEFUL_PASS') for i in range(1,6)],
                                 ('fault1','STATEFUL_FAULT_PASS'),('fault2','STATEFUL_FAULT_PASS'),('cut','STATEFUL_PASS')])
    gates['old_rom_rejection']=all(passed(ROOT/f'build/standard_migration/extended/profile_reject_{code}.log','INDEX_REJECT_PASS') for code in [8,9,10,11,16,17,30])
    checksum=ROOT/'build/standard_migration/full36/source.sha256'
    gates['frozen_source']=checksum.exists() and all(
        (ROOT/f).exists() and hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h
        for h,f in (line.split('  ',1) for line in checksum.read_text().splitlines()))
    complete=all(gates.values())
    rows=[]
    for p in stateful:
        for op in ['keygen','sign','verify']:
            result=results.get(p.name+'/'+op,{})
            row=dict(profile=p.name,operation=op,h=p.h,node_bytes=32,chain_count=67,
                standard_typecode=f'0x{p.typecode:02x}',lmots_typecode='0x0b' if p.family=='lms' else '',
                cycles=result.get('cycles'),hashes=result.get('hashes'),permutations=result.get('permutations'))
            row.update({'common_'+k:v for k,v in (common or {}).items()})
            row.update({'top_'+k:v for k,v in (tops[p.name] or {}).items()})
            rows.append(row)
    data=dict(schema='mhbs.standard.migration.v1',complete=complete,gates=gates,pipeline=4,unroll=1,
              full36=status,retained_full30=retained,common=common,tops=tops,results=rows,
              area_scope='OOC synthesis, xc7a200tffg1156-3, Vivado 2025.2, stats off; top=Sign with fixed fixture keys and ROM, signature store enabled',
              routed_sta=False,old_experimental_atp_comparable=False)
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.with_suffix('.json').write_text(json.dumps(data,indent=2)+'\n')
    with REPORT.with_suffix('.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    state_label='用户已停止两组h=20全树运行，完整36项验收未完成' if status.get('stopped_by_user') else ('全部完成' if complete else '执行中，尚未满足全部验收项')
    lines=['# SHAKE256 XMSS/LMS 六参数标准迁移（2026-10-13）','',
        f'验收状态：{state_label}。完整 RTL 三操作通过 {len(results)}/36 项。未完成实测周期留空。运行时间预测独立记录于 [h=20预测报告](../h20_stopped/Stateful_h20_Runtime_Forecast_20261013.md)，不作为实测验收结果。','',
        '## 参数与接口','',
        '六组状态参数按 h 命名，固定32字节 SHAKE256输出、67条链。XMSS采用基数16；LMS采用RFC位数4。标准依据为 [SP 800-208](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-208.pdf)、[RFC 8391](https://www.rfc-editor.org/rfc/rfc8391.html) 和 [RFC 8554/9858](https://www.rfc-editor.org/rfc/rfc9858.html)。','',
        '| 参数 | h | 标准类型码 | 公钥字节 | 签名字节 |','|---|---:|---:|---:|---:|']
    lines += [f'| {p.name} | {p.h} | 0x{p.typecode:02x} | {p.keygen_bytes} | {p.signature_bytes} |' for p in stateful]
    lines += ['', 'LM-OTS统一类型码0x0B；内部ROM配置码0x18～0x1D与标准类型码分离，旧omega名称及实验ROM码拒绝执行。TREE高度高位使用描述符bit39；程序/模板/描述符容量仍为16/16/32字。叶索引20位、遍历及LMS节点号21位、树层5位，栈与认证路径20层；端点与签名缓存容量保持原规模。','',
        '周期及Hash/置换统计全链路为64位，统计关闭时综合检查禁止残留统计寄存器。Keygen仅输出标准公钥，不输出密钥材料。Verify保留节点接口，由`hardware_verify_input`先检查标准公钥、签名长度、类型及q，再拆分节点。随机输入和q持久化仍由调用方提供；本次不宣称密码模块认证。','',
        '## 综合面积','',
        '同器件、通用Keccak映射、P4U1、统计关闭、OOC综合。top按Sign实例化，启用完整签名缓存，固定相应ROM、种子及根；common接受运行时Job/ROM，因此两者面积口径不同。等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。','',
        '| 综合顶层/参数 | LUT | FF | BRAM36等效 | 等效Slice |','|---|---:|---:|---:|---:|']
    for name,area in [('common',common),*tops.items()]:
        if area:lines.append(f'| {name} | {int(area["lut"]):,} | {int(area["ff"]):,} | {area["bram36"]:g} | {area["equivalent_slice"]:,.3f} |')
    lines += ['', '这些是综合面积，未进行本轮布局布线，不能据此宣称150 MHz闭合或实际STA频率下ATP改善。标准化与容量扩展后建立新基线，历史实验报告保留。','',
        '## 完整RTL实测','', '| 参数 | Keygen周期 | Sign周期 | Verify周期 |','|---|---:|---:|---:|']
    def cycles(name,op):
        value=results.get(name+'/'+op,{}).get('cycles');return f'{value:,}' if value is not None else '待完成'
    lines += [f'| {p.name} | {cycles(p.name,"keygen")} | {cycles(p.name,"sign")} | {cycles(p.name,"verify")} |' for p in stateful]
    lines += ['', '全树运行逐拍执行生产RTL，检查每个输出字节、Sign缓存同步读回、实际Hash/置换完成事件及64位硬件统计。C++驱动不替换Keccak或控制器，也不外推周期。SystemVerilog测试台执行停顿、截断、复位重放、在途异常和兼容检查。','',
        '## 独立参考与验收证据','',
        'XMSS参考固定为`171ccbd26f098542a67eb5d2b128281c80bd71a6`；Cisco LMS参考固定为`cea4dda4f937e56ab42e1a74665f6397473a2838`。验证适配增加SHAKE256后端和RFC9858类型映射；XMSS参考的最后索引签名在使用密钥前清零，适配修正耗尽判断，使最后合法叶仍可签名。适配补丁、实际编译源码和校验单独归档。h10独立C与Python模型的公钥、签名及计数逐项匹配。','',
        '| 检查 | 状态 |','|---|---|']
    lines += [f'| {key} | {"通过" if value else "待完成"} |' for key,value in gates.items()]
    lines += ['', '重现入口：`python3 scripts/build_stateful_reference.py`、`python3 -m model.vectors`、`python3 scripts/check_standard_models.py`、`python3 -m scripts.validate_standard`、`scripts/validate_p4.sh`、`scripts/synth_top.tcl`、`python3 scripts/report_standard.py --require-complete`。','']
    REPORT.with_suffix('.md').write_text('\n'.join(lines))
    if args.require_complete and not complete:raise SystemExit('STANDARD_REPORT_INCOMPLETE')
    if complete:
        ARCHIVE.mkdir(parents=True,exist_ok=True)
        for name in ['common',*tops]:
            src=ROOT/'build/synth/P4U1_generic' if name=='common' else ROOT/'build/synth/top_P4U1_generic'/name
            dst=ARCHIVE/'synthesis'/name;dst.mkdir(parents=True,exist_ok=True)
            for f in src.iterdir():
                if f.suffix in ('.rpt','.log','.txt','.json'):shutil.copyfile(f,dst/f.name)
        src=ROOT/'build/reference_native';dst=ARCHIVE/'reference';dst.mkdir(exist_ok=True)
        for name in ['manifest.json','adapter.patch','compile.log']:shutil.copyfile(src/name,dst/name)
        for name in ['xmss','lms']:
            shutil.copytree(src/name,dst/name,dirs_exist_ok=True)
            checkout=ROOT/f'build/reference_{name}'
            for file in checkout.iterdir():
                if file.is_file() and ('license' in file.name.lower() or file.name.lower()=='readme'):
                    shutil.copyfile(file,dst/name/file.name)
        shutil.copytree(ROOT/'build/standard_migration/source',ARCHIVE/'source',dirs_exist_ok=True)
        for file in (ROOT/'build').glob('standard*.log'):
            shutil.copyfile(file,ARCHIVE/file.name)
        shutil.copyfile(ROOT/'build/standard_migration/full36.log',ARCHIVE/'full36.log')
        shutil.copytree(ROOT/'build/recipe_check',ARCHIVE/'recipes',ignore=shutil.ignore_patterns('obj'),dirs_exist_ok=True)
        shutil.copytree(ROOT/'build/pipeline_check',ARCHIVE/'pipeline',ignore=shutil.ignore_patterns('obj'),dirs_exist_ok=True)
        shutil.copytree(ROOT/'build/standard_migration/full36',ARCHIVE/'full36',dirs_exist_ok=True)
        shutil.copytree(ROOT/'build/standard_migration/edge_rtl',ARCHIVE/'edge_rtl',dirs_exist_ok=True)
        shutil.copytree(ROOT/'build/standard_migration/extended',ARCHIVE/'extended',dirs_exist_ok=True)
        paths=(ROOT/'sources.txt').read_text().splitlines()+[str(p.relative_to(ROOT)) for folder in ['model','scripts','tb'] for p in (ROOT/folder).glob('**/*') if p.is_file() and p.suffix in ('.py','.sh','.tcl','.sv','.cpp','.c','.mem')]
        hashes={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in paths}
        source=dict(schema='mhbs.standard.source.v1',base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),profiles=list(PROFILES),operations=['keygen','sign','verify'],sha256=hashes)
        (ROOT/'SOURCE.json').write_text(json.dumps(source,indent=2)+'\n')
        (ROOT/'VALIDATION.json').write_text(json.dumps(data,indent=2)+'\n')
        (ARCHIVE/'index.json').write_text(json.dumps(source,indent=2)+'\n')
    print('STANDARD_REPORT', 'COMPLETE' if complete else 'PENDING')

if __name__=='__main__':main()
