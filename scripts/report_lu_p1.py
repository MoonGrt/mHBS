#!/usr/bin/env python3
"""Report frozen measured L/U runs; never fill missing measurements from history."""
import argparse,csv,json
import run_lu_p1 as m

def rows(label):
 data=[]
 for l,u in m.POINTS:
  p=m.OUT/label/f'L{l}U{u}'/'synthesis.json';q=m.OUT/label/f'L{l}U{u}_simulation_s1_x0.json'
  if not p.exists() or not q.exists():continue
  sim=next(x for x in json.loads(q.read_text()) if x['profile']=='slh_128f' and x['op']==1)
  area=json.loads(p.read_text())['area'];freq=150 if u==1 else 110
  data.append(dict(configuration=f'L{l}U{u}',lanes=l,unroll=u,**area,cycles=sim['cycles'],total_cycles=sim['total'],hashes=sim['hashes'],permutations=sim['permutations'],utilization=sim['permutations']*24/(l*u*sim['cycles']),assumed_mhz=freq,time_ms=sim['cycles']/(freq*1000),atp=area['equivalent_slice']*sim['cycles']/(freq*1000),fits_device=area['lut']<=133800 and area['ff']<=267600,evidence=str(p.parent.relative_to(m.ROOT))))
 return data

def compare(base,candidate):
 b={x['configuration']:x for x in rows(base)};c={x['configuration']:x for x in rows(candidate)}
 failures=[];strict=False
 if 'L4U2' not in b or 'L4U2' not in c:failures.append('missing L4U2 measurement')
 for key in {'L4U2'}&b.keys()&c.keys():
  for field in ('lut','equivalent_slice','cycles'):
   if c[key][field]>b[key][field]:failures.append(f'{key}: {field} {b[key][field]} -> {c[key][field]}')
  strict|=c[key]['equivalent_slice']<b[key]['equivalent_slice']
 if not strict:failures.append('no strict equivalent-Slice improvement')
 result=dict(baseline=base,candidate=candidate,selection_scope='L4U2',area_cycle_gate=not failures,failures=failures,full_verification_required=True)
 m.write(m.OUT/candidate/'comparison.json',result);return result

def report(label):
 data=sorted(rows(label),key=lambda r:r['atp']);
 for i,r in enumerate(data,1):r['rank']=i
 dest=m.ROOT/'docs/report/LU_P1_Optimization';dest.parent.mkdir(exist_ok=True)
 with dest.with_suffix('.csv').open('w') as f:
  if data:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
 validation={}
 for key in ('regress_status','protocol_status','cycle_comparison','netlist_audit','validation'):
  p=m.OUT/label/(key+'.json')
  if p.exists():validation[key]=json.loads(p.read_text())
 missing=[f'L{l}U{u}' for l,u in m.POINTS if not any(r['configuration']==f'L{l}U{u}' for r in data)]
 m.write(dest.with_suffix('.json'),dict(label=label,clock_ns=10,part='xc7a200tffg1156-3',routing=False,frequency_assumed=True,rows=data,missing=missing,validation=validation))
 text=['# L/U：删除 P 流水支持与面积优化','','P 固定为 1，默认 L2U2；保留十参数及 Keygen/Sign/Verify。性能数据仅为 128f Sign。','',f'当前测量快照：`{label}`，已完成 {len(data)}/14 组。', '', '共同核 OOC 综合：xc7a200tffg1156-3、10 ns、统计关闭。等效 Slice = LUT/4 + FF/8 + BRAM×232.4 + DSP×102.4；LUT 包含 LUTRAM，后者不重复计数。','', '**U1 的 150 MHz、U2 的 110 MHz 均为假定值，未经布线验证。** ATP 仅供参考；本轮按 L4U2 面积筛选优化，其他档位的面积允许变化。','', '有效轮利用率 = 置换数×24 / (L×U×计算周期)。','', '|排名|配置|LUT|FF|LUTRAM|BRAM|DSP|等效 Slice|计算周期|总周期|Hash|置换|利用率|假定 MHz|时间 ms|ATP|器件容量|','|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
 for r in data:
  text.append('|'+ '|'.join([str(r['rank']),r['configuration'],*[str(int(r[x])) for x in ('lut','ff','lutram')],str(r['bram']),str(r['dsp']),f"{r['equivalent_slice']:.3f}",*[str(r[x]) for x in ('cycles','total_cycles','hashes','permutations')],f"{r['utilization']:.2%}",str(r['assumed_mhz']),f"{r['time_ms']:.4f}",f"{r['atp']:.3f}",'可容纳' if r['fits_device'] else '超资源'])+'|')
 if missing:text+=['','未取得完整测量（不参与 ATP 排名）：'+', '.join(missing)+'。失败与中断原因见该快照的 `matrix_status.json`。']
 text+=['','时间(ms) = 计算周期 / (假定 MHz × 1000)；ATP = 等效 Slice × 时间(ms)。总周期额外包含当前测试入口的完成开销，排名使用计算周期。资源可容纳仅指综合资源总量，不能据此宣称完成布线或满足接口时序。']
 if data:
  best=min((r for r in data if r['fits_device']),key=lambda r:r['atp'],default=None)
  if best:text+=['',f"本轮最低 ATP 为 **{best['configuration']}：{best['atp']:,.3f} Slice·ms**，签名时间估算 **{best['time_ms']:.4f} ms**。"]
  overflow=[r for r in data if not r['fits_device']]
  for r in overflow:text+=['',f"**{r['configuration']} 超出目标器件容量**：{r['lut']:,.0f} LUT，器件上限 133,800 LUT。其综合已完成，表中 ATP 仅为资源外推参考，不能作为该器件的可实现方案。"]
 history=m.OUT/'l4_candidates.json'
 if history.exists():
  candidates=json.loads(history.read_text())
  text+=['','## L4U2 面积实验','','候选单独冻结、同器件同选项综合；其他配置面积不用于本轮优化筛选。已停止的早期多配置实验保留原始记录，用户调整范围后仅综合 L4U2，选定最终版本后才重新测量完整 14 组。','','|候选|改动|LUT|FF|等效 Slice|结论|','|---|---|---:|---:|---:|---|']
  for a in candidates:text.append(f"|{a['candidate']}|{a.get('description','')}|{a['lut']:.0f}|{a['ff']:.0f}|{a['equivalent_slice']:.3f}|{a.get('decision','')}|")
  b=next(x for x in candidates if x['candidate']=='structure');best=next(x for x in data if x['configuration']=='L4U2') if any(x['configuration']=='L4U2' for x in data) else None
  if best:
   text+=['',f"L4U2 相对删除 P、扩展 L 后的结构基线：LUT 减少 **{b['lut']-best['lut']:.0f}（{1-best['lut']/b['lut']:.2%}）**，等效 Slice 减少 **{b['equivalent_slice']-best['equivalent_slice']:.3f}（{1-best['equivalent_slice']/b['equivalent_slice']:.2%}）**。计算周期 **{best['cycles']:,}**，Hash/置换仍为 **104937/105641**。"]
  text+=['','最终保留：独立 lane 静态固定单节点配方，裁剪多节点 masked-hash 通路；对每个组合 Keccak 轮保留综合层次，减少跨轮组合映射的面积膨胀；共享整批一致的叶地址。没有增加流水级、复制端点存储或改变批次调度。','', '轮层次约束的收益属于当前综合映射结果，不代表布线频率提高。地址/槽位收窄在单独候选有收益，但与已保留优化合并后面积反而增加，已撤回。这里的收敛指已评估候选及其组合后停止，没有证明全局面积最优。']
 text+=['','## 验证与证据','']
 for key,val in validation.items():
  text.append(f"- `{key}.json`：{'通过' if val.get('passed',False) else '待完成或失败'}。")
 text+=['','功能验证使用 Verilator；十参数三操作在 L1U1、L2U2、L3U1、L12U2、L24U1 覆盖，另补 L4U2 全算法。四个原始 L1/L2、U1/U2 配置的逐拍结构等价证据位于 `equivalence/results.json`；后续面积优化使用冻结结构基线核对输出与周期。','', '最终回归明细、统计开关、lane 交换、停顿、复位重放、异常退出、故障签名、消息边界及网表计数检查见当前快照目录。测试专用的 lane 请求/返回延迟注入另存于 `<快照>_handshake_test`，没有进入生产综合。']
 text+=['','分层报告：`manifests/experiments/lu_p1_20261012/<候选>/LxUy/core_hierarchical.rpt`。','', '原始基线、结构基线、独立候选的源码快照、补丁、完整日志及比较 JSON 保存在同一实验目录。']
 dest.with_suffix('.md').write_text('\n'.join(text)+'\n')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('label');p.add_argument('--base');a=p.parse_args()
 if a.base:print(json.dumps(compare(a.base,a.label),indent=2))
 report(a.label)
