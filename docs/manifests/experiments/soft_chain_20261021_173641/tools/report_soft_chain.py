#!/usr/bin/env python3
"""Summarize a completed, frozen software-CHAIN experiment (JSON/Markdown)."""
import argparse,hashlib,json,re,subprocess
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path);a=p.parse_args();out=a.archive.resolve();root=out.parents[3]
 state=json.loads((out/'VALIDATION_SUMMARY.json').read_text());source=json.loads((out/'SOURCE.json').read_text());baseline=json.loads((out/'C1_VALIDATION_SUMMARY.json').read_text());areas=json.loads((out/'C1_SYNTHESIS_SUMMARY.json').read_text())
 if not state['complete']:raise SystemExit('Experiment still running; no final analysis written')
 candidates={};targets=[]
 for b in ('shake','sha2'):
  row=dict(state['synthesis'].get(b,{}));old=areas[b]
  if row.get('status')=='passed':
   row['area_change_percent']=(row['equivalent_slice']/old['equivalent_slice']-1)*100
   text=(out/'synthesis'/b/'timing.rpt').read_text()
   m=re.search(r'WNS\(ns\).*?\n\s*-.*?\n\s*([-\d.]+)',text,re.S)
   row['synthesis_wns_ns']=float(m[1]) if m else None
  candidates[b]=row
  for n in ('slh_128f','xmss_h10','lms_h10'):
   key=f'{b}/{n}/sign';v=state['tests'][key];ref=baseline['tests'][key]
   record=dict(backend=b,profile=n,status=v['status'],baseline_cycles=ref['cycles'])
   if v['status']=='passed':
    record.update(cycles=v['cycles'],cycles_change_percent=(v['cycles']/ref['cycles']-1)*100,time_ms_assumed_100mhz=v['cycles']/100000,hashes=v['hashes'],blocks=v['permutations'],dynamic_instructions=v['macro_metrics']['dynamic_instructions'],recipe_requests=v['macro_metrics']['recipe_requests'])
    if row.get('status')=='passed':
     oldatp=old['equivalent_slice']*ref['cycles']/100000;atp=row['equivalent_slice']*v['cycles']/100000
     record.update(atp_slice_ms=atp,baseline_atp_slice_ms=oldatp,atp_change_percent=(atp/oldatp-1)*100)
   targets.append(record)
 checkcounts={s:sum(r.get('status')==s for r in state['checks'].values()) for s in ('passed','failed','running')}
 result=dict(complete=state['complete'],passed=state['passed'],source=source,production_commit='9a85d79',c1_snapshot='39477f5',baseline_area=areas,area=candidates,sign_targets=targets,regression_counts=state['counts'],check_counts=checkcounts,images=state['images'],rom=dict(program_words=256,template_words=32,descriptor_words=32,total_bits=20480,c1_total_bits=12288,delta_bytes=1024),high_full_tree_tested=False,routed=False,frequency='100MHz assumed, no route closure assertion')
 report=out/'reports/Analysis.json';report.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
 lines=['# C1 → 软件 CHAIN 对照','',f"完成：{state['complete']}；验收：{state['passed']}。候选实现提交 `9a85d79`，C1 快照 `39477f5`。",'','保持复合 Hash 配方，只改变 CHAIN 控制归属。K1U1、单通道，两后端；20组参数、44项默认整核与12项补充Sign。','',f"整核结果：{state['counts']}；附加检查：{checkcounts}。所有通过项逐字节核对输出和签名缓存，保持C1的Hash/块数及前像/完整结果指纹。六项Verify另比较有序逐Hash指纹，分别核对C1和候选RTL与VM。指纹属于概率性检查。",'','## 综合面积','', '| 后端 | C1 LUT | 新 LUT | C1 FF | 新 FF | 新 BRAM/DSP | C1 等效Slice | 新等效Slice | 面积变化 | 100MHz综合WNS/ns |','|---|---:|---:|---:|---:|---|---:|---:|---:|---:|']
 for b,row in candidates.items():
  old=areas[b]
  if row.get('status')=='passed':lines.append(f"| {b} | {old['lut']:,} | {row['lut']:,} | {old['ff']:,} | {row['ff']:,} | {row['bram']}/{row['dsp']} | {old['equivalent_slice']:.3f} | {row['equivalent_slice']:.3f} | {row['area_change_percent']:+.3f}% | {row['synthesis_wns_ns']} |")
  else:lines.append(f"| {b} | {old['lut']:,} | — | {old['ff']:,} | — | — | {old['equivalent_slice']:.3f} | — | — | — |")
 lines+=['','共同核OOC，器件xc7a200tffg1156-3、Vivado2025.2、2线程、默认时序驱动综合、10ns约束；面积不含ROM和签名缓存。等效Slice=LUT/4+FF/8。负WNS表示该综合诊断路径未达到10ns；没有布局布线，100MHz只用于假定ATP，不是测得Fmax。']
 for n in ('slh_128f','xmss_h10','lms_h10'):
  lines+=['',f'## {n} Sign','', '| 后端 | C1周期 | 新周期 | 周期变化 | 新时间/ms | C1 ATP | 新 ATP | ATP变化 |','|---|---:|---:|---:|---:|---:|---:|---:|']
  for r in targets:
   if r['profile']==n and 'atp_slice_ms' in r:lines.append(f"| {r['backend']} | {r['baseline_cycles']:,} | {r['cycles']:,} | {r['cycles_change_percent']:+.3f}% | {r['time_ms_assumed_100mhz']:.6f} | {r['baseline_atp_slice_ms']:.6f} | {r['atp_slice_ms']:.6f} | {r['atp_change_percent']:+.3f}% |")
 lines+=['','ATP单位Slice·ms，ATP=等效Slice×周期/100000，均按假定100MHz；不同后端分别比较。']
 winners=[r for r in targets if r.get('atp_change_percent',0)<0]
 lines+=['', '本次控制归属实验的实测结论：共同核面积缩小，六项目标周期均增加。按假定100MHz，仅'+('、'.join(r['backend']+'/'+r['profile'] for r in winners) if winners else '无目标')+'的面积收益足以抵消周期代价，其余ATP增加。该判断只适用于本候选和此假定频率。', '新增控制成本来自逐链/逐步取指、条件判断、节点访问及软件归约；Hash前像、结果和工作量保持不变。SHA2 XMSS使用复合KEY/MASK配方且压缩计算较长，其控制开销占比较低，这是该目标表现不同的合理解释；不把该解释推广为其他实现的必然排序。','', '## 程序和控制开销','','ROM为256/32/32个64位字，总20,480位（2,560字节）。C1为128/32/32，总12,288位，增加1,024字节。共同核面积没有包含这部分ROM增量。','', '| 类型 | 有效program | 有效template | 可达descriptor | CHAIN/TREE模板 |','|---|---:|---:|---:|---|']
 for n in ('slh_128f','xmss_h10','lms_h10'):
  u=state['images'][f'shake/{n}']['usage'];lines.append(f"| {n} | {u['program_used']} | {u['template_used']} | {u['descriptor_used']} | 0/0 |")
 lines+=['','描述符有效数量按从实际模板可达的记录统计，包含语义有效的零值记录；完整32字ROM仍保留C1的未引用记录，JSON另含valid/nonzero统计。20组镜像逐个检查容量、标识、后端和权限，生成可重现。','', '| 后端/目标 | 动态指令数 | 配方请求数 | 完整Hash数 | 块数 |','|---|---:|---:|---:|---:|']
 for r in targets:
  if 'dynamic_instructions' in r:lines.append(f"| {r['backend']}/{r['profile']} | {r['dynamic_instructions']:,} | {r['recipe_requests']:,} | {r['hashes']:,} | {r['blocks']:,} |")
 lines+=['','HASH模板每次最多授权一次现有复合配方，完成反馈不推进链号或链步。XMSS KEY/MASK、SHA2 HMAC/MGF1仍在原配方中，因而“配方请求数”和标准Hash统计并不总是相等。所有CHAIN/TREE动态次数为零。','', '## 验证边界与证据','','h16/h15/h20只测真实高度Verify，未运行其完整Keygen/Sign。h20完整树保持停止。补充Sign只用h10的q=1/1023和空消息。','', '控制测试覆盖两层CALL成功、第三层溢出、空栈RET、旧布局、非法CHAIN/TREE模板和只读/越界访问；另验证停顿、复位、截断、篡改、q越界、两后端配方边界与SYNTHESIS视图。统计综合裁剪通过debug_audit.json核查。','', '完整原像/结果的SUM/XOR指纹和有序指纹之外，输出及签名缓存逐字节核对。外部输入、期望数据、元数据均与认证C1字节一致，只替换三个ROM；见INDEPENDENT_IMPLEMENTATION_AUDIT.json。','', '源码和镜像身份见SOURCE.json、IMAGE_SUMMARY.json、BASELINE_RELATIONSHIP.json；冻结RTL见frozen_rtl.tar.gz；综合分层、时序及日志在synthesis/下；详细仿真日志保留在build/soft_chain/20261021_173641。原image-chain和image-chain-tree未修改。']
 (out/'reports/Analysis.md').write_text('\n'.join(lines)+'\n')
 tools=out/'tools';tools.mkdir(exist_ok=True);tool=Path(__file__).resolve();(tools/tool.name).write_bytes(tool.read_bytes())
 (out/'ARTIFACTS.json').write_text(json.dumps(dict(complete=state['complete'],passed=state['passed'],sha256={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='ARTIFACTS.json'}),indent=2)+'\n')
 print(report)
if __name__=='__main__':main()
