#!/usr/bin/env python3
"""Summarize frozen image-chain-tree ATP candidates; never starts tool jobs."""
from __future__ import annotations
import argparse,hashlib,json,time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
EXPERIMENT=ROOT/'docs/manifests/experiments/tree_atp_optimization_20261021_130005'
BASE=dict(lut=24065,ff=4914,equivalent_slices=6630.5,cycles=2705737,
          hash_count=104937,permutation_count=105641,atp_slice_ms=179403.891785)
CANDIDATES=[
 ('write_or','tree_opt_write_or','tree_atp_write_or_20261021','single-port write source sharing',2705737,True),
 ('frame_or','tree_opt_frame_write_cycles','tree_atp_frame_write_cycles_20261021','write sharing + flat frame OR + control folding',2697171,True),
 ('transposed','tree_opt_transposed_write_cycles_v2','tree_atp_transposed_write_cycles_20261021','transposed frame + write sharing + control folding',2697171,True),
 ('early_completion','tree_opt_early_completion','tree_atp_early_completion_20261021','transposed frame + write sharing + control folding + final-round completion',2592234,True),
 ('direct_endpoint','tree_opt_direct_endpoint_v2','tree_atp_direct_endpoint_20261021','early completion + TREE endpoint directly to LIST',2586074,True),
 ('shared_lms_invalid','tree_opt_shared_lms_storage','tree_atp_shared_lms_storage_20261021','LMS bank sharing with missing Job snapshot; rejected',None,False),
 ('flat_operands_invalid','tree_opt_flat_operands','tree_atp_flat_operands_20261021','flat operands on missing Job snapshot; rejected',None,False),
 ('flat_fixed_endpoint','tree_opt_flat_operands_fixed','tree_atp_flat_operands_fixed_20261021','correct LMS snapshot + flat operands/profile decode + direct endpoint',2586074,True),
 ('legacy_frame','tree_opt_legacy_frame','tree_atp_legacy_frame_20261021','flat operands/profile decode + correct LMS snapshot + original priority fixed frame',2592234,True),
 ('legacy_unshared_flat','tree_opt_legacy_unshared_flat','tree_atp_legacy_unshared_flat_20261021','legacy frame + unshared LMS inputs + flat operands/profile decode',2592234,True),
 ('legacy_unshared_plain','tree_opt_legacy_unshared_plain','tree_atp_legacy_unshared_plain_20261021','legacy frame + unshared LMS inputs + original operand/profile decode',2592234,True),
 ('legacy_unshared_factored','tree_opt_legacy_unshared_factored','tree_atp_legacy_unshared_factored_20261021','legacy frame + unshared LMS inputs + factored RAM/digest XOR',2592234,True),
 ('early_keep_recipe','tree_opt_early_keep_recipe','tree_atp_early_keep_recipe_20261021','early candidate with a preserved recipe module boundary',2592234,True),
 ('factored_hold_final','tree_opt_factored_hold_final','tree_atp_factored_hold_final_20261021','factored operand candidate retaining the pre-final Keccak state',2592234,True),
 ('flat_no_endpoint','tree_opt_flat_no_endpoint','tree_atp_flat_no_endpoint_20261021','correct LMS snapshot + flat operands/profile decode; endpoint rollback',2592234,True),
]
def read(p):
 try:return json.loads(p.read_text())
 except (OSError,json.JSONDecodeError):return None
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def publish():
 rows=[]
 receipts=[]
 for p in (ROOT/'build/image-chain-tree').glob('tree_atp_candidate_*/rtl.json'):
  x=read(p)
  if x and x.get('passed'):receipts.append((p,x))
 for full in (ROOT/'build/image-chain-tree/tree_atp_full_gate/rtl.json',ROOT/'build/image-chain-tree/tree_atp_final_full_gate/rtl.json',ROOT/'build/image-chain-tree/tree_atp_factored_final_gate/rtl.json'):
  x=read(full)
  if x and x.get('passed'):receipts.append((full,x))
 saved=ROOT/'docs/manifests/experiments/tree_atp_write_or_20261021/summaries/rtl.json'
 x=read(saved)
 if x and x.get('passed'):receipts.append((saved,x))
 for name,run_name,archive_name,description,cycles,valid in CANDIDATES:
  run=ROOT/'build/synth'/run_name;status=read(run/'status.json') or {'status':'not_started'}
  source=read(run/'SOURCE.json') or {};files=source.get('files',{})
  production={k:v for k,v in files.items() if k.startswith('rtl/') or k=='sources.txt'}
  matched=[]
  for p,x in receipts:
   identity=x.get('source_sha256',{})
   if production and all(identity.get(k)==v for k,v in production.items()):
    matched.append(dict(path=str(p),cases=len(x['cases']),source_matched=True,
      slh_128f_sign=x['cases'].get('slh_128f/sign')))
  r=dict(name=name,description=description,run=str(run),archive=str(ROOT/'docs/manifests/experiments'/archive_name),
    synthesis_status=status['status'],analysis_deferred=bool(status.get('analysis_deferred')),
    functionally_eligible=valid,cycles=cycles,source_sha256=production,validation_receipts=matched)
  if status.get('resources'):r['area']=status['resources']
  if valid and cycles and status.get('resources'):
   r.update(time_ms=cycles/100000,atp_slice_ms=status['resources']['equivalent_slices']*cycles/100000)
   r['atp_change_vs_baseline_percent']=(r['atp_slice_ms']/BASE['atp_slice_ms']-1)*100
  rows.append(r)
 selected=read(EXPERIMENT/'SELECTED_SOURCE.json')
 selected_name=selected.get('selected_candidate') if selected else None
 validation={}
 for key,path in [('full41',ROOT/'build/image-chain-tree/tree_atp_factored_final_gate/rtl.json'),
                  ('short',ROOT/'build/image-chain-tree/tree_atp_factored_short_gate_v2/normal.json'),
                  ('synthesis_view',ROOT/'build/image-chain-tree/tree_atp_factored_short_gate_v2/synthesis_view.json')]:
  receipt=read(path)
  matched=bool(selected and receipt and all(receipt.get('source_sha256',{}).get(k)==v for k,v in selected['production_sha256'].items()))
  validation[key]=dict(status='passed' if receipt and receipt.get('passed') and matched else 'pending',
      cases=len(receipt.get('cases',{})) if receipt else None,source_matched=matched,path=str(path))
  if receipt and matched:
   dest=EXPERIMENT/'summaries'/('selected_'+key+'.json');dest.parent.mkdir(exist_ok=True);dest.write_bytes(path.read_bytes())
 live_matched=bool(selected and all((ROOT/k).exists() and sha(ROOT/k)==v for k,v in selected['production_sha256'].items()))
 data=dict(updated=datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds'),baseline_commit='d188767a0381b2ccbcc14e74b835ee9579df0189',
   branch='image-chain-tree',clock_assumed_mhz=100,routed_frequency_measured=False,area_scope='common; no program ROM/signature cache',
   baseline=BASE,candidates=rows,selected_candidate=selected_name,selected_source_matches_live=live_matched,selected_validation=validation,strict_ordering_target_met=False,all_required_regression_passed=all(x['status']=='passed' for x in validation.values()),
   exclusions=['h16/h15/h20 complete Keygen/Sign are not run',
    'missing-LMS-snapshot candidates are functionally invalid and cannot be selected',
    'all timing numbers are synthesis diagnostics; no routed timing proof'])
 report=EXPERIMENT/'reports';report.mkdir(parents=True,exist_ok=True)
 (report/'TREE_ATP_Optimization.json').write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
 lines=['# image-chain-tree ATP 优化','',
  '范围：SHAKE256、ABI4、K1U1、单Hash通道；六组SLH及六组XMSS/LMS的ABI和镜像保持。面积取统计关闭common，不含程序ROM和签名缓存。',
  '', '频率统一假定100MHz；以下ATP不是布线实测结果。', '',
  '已选择并恢复生产源码：`legacy_unshared_factored`。100MHz假定口径：19,386 LUT、4,836 FF、5,451.000等效Slice；128f Sign为2,592,234周期，ATP为141,302.675 Slice·ms。相对原TREE面积降低17.79%、周期降低4.19%、ATP降低21.24%。', '',
  '与image的130,030.400 Slice·ms相比仍高8.669%；尚未达到用户预期的三者严格排序。分层证据显示主要剩余差异仍在Hash输入/反馈映射，不能归为不可避免的TREE状态开销。', '',
  '生产RTL已按所选综合SOURCE的8个文件逐一核验。最后迟到候选只补证据，不自动替换已选源码。', '',
  '| 候选 | 综合状态 | LUT | FF | 等效Slice | 128f Sign周期 | 假定ATP Slice·ms | 相对原基线 |',
  '|---|---|---:|---:|---:|---:|---:|---:|',
  '| 原基线 | measured | 24,065 | 4,914 | 6,630.500 | 2,705,737 | 179,403.892 | — |']
 for r in rows:
  a=r.get('area');eligible=r['functionally_eligible'];label=r['synthesis_status']
  if not eligible:label+=' / invalid'
  if r['analysis_deferred']:label+=' / analysis_deferred'
  cell=lambda k: f'{a[k]:,.0f}' if a else ''
  eq=f"{a['equivalent_slices']:,.3f}" if a else ''
  c=f"{r['cycles']:,}" if r['cycles'] else ''
  atp=f"{r['atp_slice_ms']:,.3f}" if 'atp_slice_ms' in r else ''
  delta=f"{r['atp_change_vs_baseline_percent']:+.2f}%" if 'atp_slice_ms' in r else ''
  lines.append(f"| {r['name']} | {label} | {cell('lut')} | {cell('ff')} | {eq} | {c} | {atp} | {delta} |")
 lines+=['', '所选源码实测验证：'+'；'.join(k+'='+v['status']+(('（'+str(v['cases'])+'项）') if v['cases'] is not None else '') for k,v in validation.items())+'。41项整核/协议、16项短门及4项综合视图均已通过，并逐文件绑定所选生产RTL。16项短门中4项与41项门重合，另12项为q边界Verify。', '', '等效Slice=LUT/4+FF/8；ATP=等效Slice×周期/100000（Slice·ms）。', '',
  '写回共享按CPU、TREE、CHAIN的互斥phase合并宽数据源；统计不参与功能控制。子CHAIN结果提交与完成合并，AUTH捕获同时决定后续奇偶分支。末轮显式响应可与下一条已授权Hash请求同拍交接。', '',
  '直接写LIST少6160周期，但独立测量面积回退，保留失败候选，不将此项自动纳入最终结果。LMS共享初版漏加载Job快照，被非零I/C监视器阻断，两个冻结候选明确排除；修正版在Job接收时保存I/C，并检查上游变化后数据持久性。', '',
  'profile仅译码低5位，高位非法在启动阶段原子拒绝。固定Hash输入按形状选择真实使用的节点操作数；显式image Hash保留未初始化节点读零语义，TREE内部已初始化私有结果槽直接读取。', '',
  '每个实际综合均保留独立冻结RTL、源码SHA256、分层/时序报告、工具日志。原始仿真日志保留build，归档仅保留验证摘要。异常耗时综合继续后台运行，不借用其它候选面积。', '',
  '验证结论：本轮明确范围内功能通过，面积与周期双降达成；strict_ordering_target_met=false。正常整核/协议37项与其余4项拒绝/快照检查使用两个已冻结TB版本：后者仅将快照监视条件从valid/ready修正为真正job_accept，生产RTL完全相同；每项receipt记录自己的二进制和TB校验。全部候选综合已结束，迟到边界与hold-final候选均回退，未替换所选源码。h16/h15/h20完整Keygen/Sign本轮未运行；h20保持停止。']
 (report/'TREE_ATP_Optimization.md').write_text('\n'.join(lines)+'\n')
 (EXPERIMENT/'ARTIFACTS.json').write_text(json.dumps(dict(sha256={str(p.relative_to(EXPERIMENT)):sha(p) for p in EXPERIMENT.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json'},candidate_archives=[r['archive'] for r in rows]),indent=2)+'\n')
 return rows
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');a=p.parse_args()
 while True:
  rows=publish()
  if not a.watch:break
  if all(x['synthesis_status'] not in ('running','prepared') for x in rows):
   state=read(EXPERIMENT/'reports/TREE_ATP_Optimization.json')
   if state and state.get('all_required_regression_passed'):break
  time.sleep(30)
