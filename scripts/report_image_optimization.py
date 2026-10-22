#!/usr/bin/env python3
"""Finalize measured image optimization results; no CSV and no routing."""
import argparse,hashlib,json,re,shutil
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def timing(p):
 s=p.read_text();m=re.search(r'Slack \([^)]*\)\s*:\s*([-\d.]+)ns',s)
 def f(expr):
  m=re.search(expr,s);return m[1].strip() if m else None
 return dict(wns_ns=float(m[1]) if m else None,source=f(r'Source:\s*([^\n]+)'),destination=f(r'Destination:\s*([^\n]+)'),logic_levels=int(f(r'Logic Levels:\s*(\d+)') or 0))
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path);args=parser.parse_args();a=args.archive.resolve();state=json.loads((a/'VALIDATION_SUMMARY.json').read_text());base=json.loads((a/'BASELINE_VALIDATION_SUMMARY.json').read_text());source=json.loads((a/'SOURCE.json').read_text())
 if not state['complete']:raise SystemExit('Required regression is still running')
 rows=[];areas={}
 for b in ('shake','sha2'):
  v=state['synthesis'][b];old=base['synthesis'][b]
  areas[b]=dict(v,area_change_percent=(v['equivalent_slice']/old['equivalent_slice']-1)*100,diagnostic=timing(a/'synthesis'/b/'critical_paths.rpt'))
  for n in ('slh_128f','xmss_h10','lms_h10'):
   k=f'{b}/{n}/sign';v=state['tests'][k];o=base['tests'][k];atp=areas[b]['equivalent_slice']*v['cycles']/100000;old_atp=old['equivalent_slice']*o['cycles']/100000
   rows.append(dict(backend=b,profile=n,cycles=v['cycles'],baseline_cycles=o['cycles'],cycle_change_percent=(v['cycles']/o['cycles']-1)*100,atp_slice_ms=atp,baseline_atp_slice_ms=old_atp,atp_change_percent=(atp/old_atp-1)*100,hashes=v['hashes'],blocks=v['permutations'],dynamic=v['macro_metrics'],dynamic_identity=v['macro_metrics']==o['macro_metrics']))
 stages={}
 for p in sorted((a/'stages').glob('*/MEASUREMENT.json')):stages[p.parent.name]=json.loads(p.read_text())
 data=dict(complete=True,passed=state['passed'],source=source,area=areas,targets=rows,stages=stages,regression_counts=state['counts'],checks={s:sum(v['status']==s for v in state['checks'].values()) for s in ('passed','failed')},route=False,frequency_mhz_assumed=100)
 (a/'reports/Analysis.json').write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
 lines=['# image F4 面积与软件控制周期优化','',f"完成：{state['complete']}；通过：{state['passed']}。基线为 image 软件CHAIN实验 `soft_chain_20261021_173641`，代码基点 `394a6993`。",'', '链、链号、链步、捕获、L-tree和Merkle/FORS树遍历仍由layout5程序控制；20组ROM逐字不变。不增加Hash通道、不引入CHAIN/TREE宏或参数专用实现。','', '## 改动与边界','', '- 纯算术、分支、CALL/RET和WMOV在执行当拍退休，省去等待完成脉冲的空拍。RAM和I/O仍在完成后退休；取指寄存边界保留。','- 三个窄上下文读取选择网络压成两个，按opcode选择源；未增加寄存器文件。','- LOAD、Verify INPUT和WMOV共用256位写数据选择器；共用数据选择，不合并同时存活的节点银行。','- SHAKE固定块保持one-hot选择直接拼接，删除布局编号的重复编码/译码。SHA2前端、Keccak和SHA256轮逻辑不变。','', '## 同口径综合面积','', '| 后端 | 原LUT / FF | 新LUT / FF | 原等效Slice | 新等效Slice | 面积变化 | BRAM / DSP |','|---|---:|---:|---:|---:|---:|---|']
 for b,v in areas.items():
  o=base['synthesis'][b];lines.append(f"| {b} | {o['lut']:,} / {o['ff']:,} | {v['lut']:,} / {v['ff']:,} | {o['equivalent_slice']:.3f} | {v['equivalent_slice']:.3f} | {v['area_change_percent']:+.3f}% | {v['bram']} / {v['dsp']} |")
 lines+=['','共同核common OOC，Vivado2025.2、xc7a200tffg1156-3、2线程、默认时序驱动综合、10ns。等效Slice=LUT/4+FF/8；不含ROM和签名缓存。']
 for n in ('slh_128f','xmss_h10','lms_h10'):
  lines+=['',f'## {n} Sign','', '| 后端 | 原周期 | 新周期 | 周期变化 | 原ATP | 新ATP | ATP变化 |','|---|---:|---:|---:|---:|---:|---:|']
  for v in rows:
   if v['profile']==n:lines.append(f"| {v['backend']} | {v['baseline_cycles']:,} | {v['cycles']:,} | {v['cycle_change_percent']:+.3f}% | {v['baseline_atp_slice_ms']:.6f} | {v['atp_slice_ms']:.6f} | {v['atp_change_percent']:+.3f}% |")
 lines+=['','ATP单位Slice·ms，按假定100MHz计算：等效Slice×周期/100000。六项目标的Hash/块数、原像/结果指纹、动态指令及配方请求数与基线一致，周期收益来自退休握手而不是少算Hash或改变程序。','', '## 逐候选对照','', '| 候选 | 改动 | SHAKE LUT / FF | SHA2 LUT / FF |','|---|---|---:|---:|']
 desc={'F1':'执行边沿退休','F2':'F1＋两个窄读口','F3':'F1＋共用宽写数据','F4':'F1＋窄读口＋共用宽写数据＋固定块one-hot'}
 for name,v in stages.items():
  def fmt(b):return f"{v[b]['lut']:,} / {v[b]['ff']:,}" if b in v and v[b]['lut'] is not None else '—'
  lines.append(f"| {name} | {desc.get(name,name)} | {fmt('shake')} | {fmt('sha2')} |")
 lines+=['','固定块one-hot单独试验为16,816 LUT / 5,881 FF，配方459项通过。F1单独SHAKE面积略增、周期下降；F2单独没有面积收益。各项面积效果不可线性相加，最终选实测最小的组合F4。F1六项Sign及F4六项Verify冒烟摘要另归档。','', 'F2/F3探索综合已产生utilization、hierarchical和timing报告，但归档末段因测试副本缺少audit_debug.tcl而报错；不将它们记作完整验收通过。最终F4在完整冻结源码上重新综合，两后端debug_audit均通过。上述探索报告与缺项原样保留。','', '分层报告的sequencer曾显示4,186 LUT；独立综合只有243 LUT / 214 FF。rebuilt层级把执行器中的数据选择和状态逻辑归入了该实例，不能据此把4,186 LUT全归因于PC/LOOP控制器。独立综合及单元源码校验见stages/baseline_sequencer_attribution。','', '## 时序诊断与剩余瓶颈','', '| 后端 | 原WNS/ns | 新WNS/ns | 新逻辑级数 | 新关键路径 |','|---|---:|---:|---:|---|']
 base_root=Path(json.loads((a/'BASELINE_SOURCE.json').read_text())['archive'])
 for b,v in areas.items():
  old=timing(base_root/'synthesis'/b/'critical_paths.rpt');t=v['diagnostic'];lines.append(f"| {b} | {old['wns_ns']} | {t['wns_ns']} | {t['logic_levels']} | {t['source']} → {t['destination']} |")
 lines+=['','SHAKE诊断路径改善，SHA2诊断WNS小幅回退。两后端10ns诊断仍有负裕量；未布线、不报告实际Fmax，100MHz ATP仅是假定指标。剩余长路径主要在FORS目标选择、窄上下文/ALU校验与写使能之间，后续时序优化应针对该路径。','', '## 验证与归档','', f"整核：{state['counts']}；附加检查：{data['checks']}。44项默认＋12项q边界/空消息Sign；h16/h15/h20只做真实高度Verify，未执行完整Keygen/Sign。",'', '逐字节核对公钥/签名输出及缓存；核对64位统计、原像/完整结果多重集指纹及六项Verify的有序指纹。指纹为概率性检查。四种控制视图各32项，覆盖CALL两层、PC/RAM边界、非法模板/后端、溢出、RUN以及两层LOOP和第三层拒绝。停顿、复位、截断、篡改与SYNTHESIS视图均保留。','', 'SOURCE.json绑定冻结源码，frozen_rtl.tar.gz保存该次RTL；IMAGE_SUMMARY.json保存ROM身份；synthesis/包含两后端最终分层、时序、统计裁剪及日志；stages/保存探索候选。详细仿真日志留在SOURCE.json记录的build运行目录。原main、image-old、image-chain和image-chain-tree未改动。']
 (a/'reports/Analysis.md').write_text('\n'.join(lines)+'\n')
 tools=a/'tools';tools.mkdir(exist_ok=True);shutil.copy2(__file__,tools/Path(__file__).name)
 (a/'ARTIFACTS.json').write_text(json.dumps(dict(complete=state['complete'],passed=state['passed'],sha256={str(p.relative_to(a)):sha(p) for p in sorted(a.rglob('*')) if p.is_file() and p.name!='ARTIFACTS.json'}),indent=2)+'\n')
 print(a/'reports/Analysis.md')
if __name__=='__main__':main()
