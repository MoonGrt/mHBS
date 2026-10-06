#!/usr/bin/env python3
"""Assemble measured stateful results and source-bound verification evidence."""
from legacy_lane_guard import require_legacy_lanes
require_legacy_lanes()
from pathlib import Path
import json,csv,hashlib,shutil,subprocess,tarfile
from run_stateful import OUT,ROOT
from run_lup_sign_atp import snapshot

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 area=read(OUT/'implementation/area.json');rows=[]
 old={r['point']:r for r in read(ROOT/'manifests/experiments/k1k2_p1u1_current_20261008/results.json')}
 for k in (1,2):
  r=read(OUT/f'K{k}P1U1_simulation.json');assert len(r)==12
  for s in r:
   a=area[s['point']];ms=s['compute_cycles']/150000
   rows.append(dict(**s,**a,assumed_mhz=150,time_ms=ms,atp_slice_ms=a['equivalent_slice']*ms))
 masked=read(OUT/'masked_chain/results.json');assert len(masked)==3 and all(x['passed'] for x in masked)
 edges=read(OUT/'edge_results.json');assert len(edges)==101,len(edges)
 normal={(r['profile'],r['operation']):r for r in rows if r['point']=='K2P1U1'}
 for name in ('xmss_omega2','xmss_omega4','lms_omega2','lms_omega4'):
  for label in ('stats_off','swap'):
   r=edges[name+'_'+label];assert r['compute_cycles']==normal[name,2]['compute_cycles']
 for label in ('stats_off','swap'):
  assert edges['lms_omega2_sign_'+label]['compute_cycles']==normal['lms_omega2',1]['compute_cycles']
 variants=read(OUT/'slh_variants.json');assert len(variants)==34
 oldver=read(ROOT/'manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/verify/results.json')
 curver=read(ROOT/'build/v4.2/external_job_message/stateful_verify_regression_20261008/verify/results.json');assert curver['passed']
 assert sum(map(len,curver['profiles'].values()))==130
 for name,v in curver['profiles'].items():
  for key in ('cycles','hashes','permutations','nodes'):assert v['normal'][key]==oldver['profiles'][name]['normal'][key]
 inputs=read(OUT/'implementation/inputs.json')
 for f in (ROOT/'manifests/v42_sources.txt').read_text().split():assert sha(ROOT/f)==inputs['source_sha256'][f]
 evidence=OUT/'validation';evidence.mkdir(exist_ok=True)
 # Final tests/docs snapshot is separate from the exact synthesis snapshot.
 snapshot(evidence)
 shutil.copytree(ROOT/'build/stateful_20261008/slh_variants/logs',OUT/'slh_variants_logs',dirs_exist_ok=True)
 for src,label in [(ROOT/'build/v4.2/external_job_message/stateful_slh_regression_20261008','slh_normal'),(ROOT/'build/v4.2/external_job_message/stateful_verify_regression_20261008','slh_verify'),(ROOT/'manifests/experiments/stateful_20261008/unit_evidence','units'),(ROOT/'build/stateful_20261008/frozen_kp/results','frozen_k2_middle')]:
  dest=evidence/label
  for p in src.rglob('*'):
   if p.is_file() and 'obj' not in p.parts and 'binaries' not in p.parts and p.suffix in ('.log','.json','.mem','.gz'):
    target=dest/p.relative_to(src);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
 for name in ('masked_chain.log','software.log','software_final.log','contract_lint.log','model_unit.log','store136.log','boot.log','k1.log','k2.log','slh_variants.log','lms_padding.log','k2_middle.log','frozen_kp.log','synth.log','edges_resume.log'):
  p=ROOT/'build/stateful_20261008'/name
  if p.exists():shutil.copy2(p,evidence/name)
 validation=dict(passed=True,normal_cases=24,masked_chain_unit_cases=15,stateful_edge_cases=len(edges),slh_normal_cases=12,slh_verify_cases=130,slh_variant_cases=len(variants),slh_output_cycles_unchanged=True,rtl_matches_synthesis_snapshot=True,independent_verifier='model/reference/stateful_shake.py',frozen_oracle_commit='67a1cd75',frequency_basis='assumed 150 MHz; no place/route')
 (OUT/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
 deltas={point:{key:area[point][key]-old[point][key] for key in ('lut','ff','lutram','bram36','equivalent_slice')} for point in area}
 result=dict(configuration=dict(n=32,h=10,hash='experimental SHAKE256',q=0,message_hex='42',clock_period_ns=6.666667,assumed_mhz=150,routed=False,sign_recomputes_full_tree=True,scope='common core; excludes ROM and signature cache'),baseline_commit='67a1cd75',previous_area=old,area_delta=deltas,validation=validation,points=rows)
 doc=ROOT/'docs/v4.2/Stateful_XMSS_LMS'
 text='''# XMSS/LMS 实验 SHAKE256 扩展

已实现四个参数集的 Keygen、Sign、Verify。n=32、h=10；omega2/4 表示每个数字 2/4 位，分别为 133/67 条链、最大 3/15 步。沿用冻结 `67a1cd75` 模型配方和私有编码，不宣称 RFC 参数互操作。

Sign 每次完整重算认证树，无整树缓存；q 由外部在签名前持久化占用，复位不允许重复使用。Verify 通过 R、链节点和认证节点恢复根。端点存储为 136×256 bit，XMSS 原地 L-tree、LMS 列表/叶压缩复用原树栈；新算法使用普通请求，SLH 流水批处理不变。

## 共同核面积

器件 xc7a200tffg1156-3，综合约束 6.666667 ns，统计关闭。仅综合，**150 MHz 为假定值，未经布局布线验证**。面积不含镜像 ROM 和顶层签名缓存；LUT 已含 LUTRAM，不重复计数。

| 配置 | LUT | FF | LUTRAM | BRAM | 等效 Slice | ΔLUT | Δ等效 Slice |
|---|---:|---:|---:|---:|---:|---:|---:|
'''
 for point,a in area.items():
  d=deltas[point];text+=f"| {point} | {a['lut']:,.0f} | {a['ff']:,.0f} | {a['lutram']:,.0f} | {a['bram36']:g} | {a['equivalent_slice']:,.3f} | {d['lut']:+,.0f} | {d['equivalent_slice']:+,.3f} |\n"
 text+='''
面积增量相对同约束的原 SLH 共同核：K1P1U1 为 13,725 LUT / 5,725 FF / 4146.875 Slice；K2P1U1 为 18,079 LUT / 7,939 FF / 5512.125 Slice。新增的是配方、调度和存储支持，没有新增 Keccak 引擎。

`等效 Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP`；`时间(ms)=计算周期/150000`；`ATP=等效 Slice×时间(ms)`。

## 24 组正常执行

q=0，消息为 1 字节 `42`；完整密钥/标识符输入见归档向量。总周期从复位释放计至完成，计算周期不含启动/结束的 5 拍；无外部停顿。Verify 周期依赖消息及链数字。Hash 是实际 SHAKE 调用数，XMSS masked hash 包含子哈希。Sign 包含完整树计算，不能与历史缓存命中周期直接比较。

| 配置 | 参数集 | 操作 | 计算周期 | 总周期 | Hash | 置换 | 时间 ms（估算） | ATP Slice·ms（估算） |
|---|---|---|---:|---:|---:|---:|---:|---:|
'''
 ops={0:'Keygen',1:'Sign',2:'Verify'}
 for r in rows:text+=f"| {r['point']} | {r['profile']} | {ops[r['operation']]} | {r['compute_cycles']:,} | {r['total_cycles']:,} | {r['hashes']:,} | {r['permutations']:,} | {r['time_ms']:.3f} | {r['atp_slice_ms']:.3f} |\n"
 text+='''
## 验证与证据

- 新算法：24 组正常执行通过；Keygen/Sign 逐字节对照冻结模型，Verify 对照独立 hashlib 验证器。101 项扩展覆盖 q=1/1023、越界、篡改消息/R/链/认证路径/根、消息边界、停顿、截断及复位、异常退出、统计关闭、lane 交换、P4 普通请求和默认 U2。
- 133 项链与 L-tree 奇数保留由完整树输出对照覆盖；共享存储测试覆盖 127/128 边界和奇数节点晋升；混合 4/32 字节缓存逐项读回通过。四参数正常向量均包含零步和最大步链；另有 15 项 masked chain 检查覆盖普通 P4 反馈、共享/独立状态及默认 U2，按冻结轮函数逐拍对照。
- SLH：六参数 Keygen/Sign 12 组、Verify 130 项全部通过，原输出、周期和 Hash/置换次数不变；追加 34 项统计关闭、共同核提取及 K/P 配置检查。
- 两组综合均通过统计寄存器裁剪检查；本轮无布线，无新频率结论，无提交或推送。

[全部实验资料](../../manifests/experiments/stateful_20261008/) · [K1 分层面积](../../manifests/experiments/stateful_20261008/implementation/K1P1U1/core_hierarchical.rpt) · [K2 分层面积](../../manifests/experiments/stateful_20261008/implementation/K2P1U1/core_hierarchical.rpt)

综合快照和配置位于 `implementation/`，完整最终源码补丁为 `final_changes.patch`；最终测试源码与 SLH/单元证据位于 `validation/`，正常及边界向量在 `vectors/`，日志在 `logs/`。`evidence_sha256.json` 绑定所有归档文本和源码快照。

重跑入口：`scripts/stateful_vectors.py`、`scripts/run_stateful.py --k 1/2`、`scripts/verify_stateful_edges.py`、`scripts/verify_stateful_lms_padding.py`、`scripts/verify_stateful_masked_chain.py`、`scripts/verify_stateful_slh.py`、`scripts/verify_stateful_k2_middle.py`、`scripts/synth_stateful.py`、`scripts/report_stateful.py`。修改源码应使用新的实验目录；综合与最终测试快照分别保留，不改写历史基线。
'''
 doc.with_suffix('.md').write_text(text);doc.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n')
 with doc.with_suffix('.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
 for ext in ('.md','.json','.csv'):shutil.copy2(doc.with_suffix(ext),OUT/('report'+ext))
 patch=subprocess.check_output(['git','diff','--binary'],cwd=ROOT)
 new=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
 for name in new:
  if name.split('/')[0] in ('model','scripts','tb','tests','docs'):
   r=subprocess.run(['git','diff','--no-index','--binary','--','/dev/null',name],cwd=ROOT,stdout=subprocess.PIPE)
   assert r.returncode in (0,1);patch+=r.stdout
 (OUT/'final_changes.patch').write_bytes(patch)
 hashes={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='evidence_sha256.json' and p.suffix in ('.json','.csv','.md','.log','.rpt','.sv','.py','.mem','.gz','.patch','.tcl','.xdc','.bin')}
 (OUT/'evidence_sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
 print('STATEFUL_REPORT_PASS',len(rows),len(edges),flush=True)
if __name__=='__main__':main()
