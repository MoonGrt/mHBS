from pathlib import Path
import hashlib,json,sys,subprocess,tarfile,shutil
from decimal import Decimal
root=Path(__file__).resolve().parents[4];sys.path.insert(0,str(root));from scripts import run_hash_backends as f
archive=root/'docs/manifests/experiments/image_chain_atp_20261021_125914';reports=archive/'reports';summaries=archive/'summaries'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
write=lambda p,x:Path(p).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
normal=json.loads((root/'build/hashflow/chain_atp_transposed_handoff/rtl.json').read_text())
extra=json.loads((root/'build/hashflow/chain_atp_transposed_handoff_full/rtl.json').read_text())
synthview=json.loads((root/'build/hashflow/chain_atp_E_synthesis_view/rtl.json').read_text())
protocol=json.loads((root/'build/hashflow/chain_atp_E_protocol/rtl.json').read_text())
identity=f.source_identity()
for gate in [normal,extra,synthview,protocol]:assert gate['passed'] and gate['source_sha256']==identity
cases={**normal['cases'],**extra['cases']};assert len(cases)==28
old=json.loads((root/'docs/manifests/experiments/image_chain_stateful_20261021_121656/summaries/rtl.json').read_text())['cases']
for name,row in cases.items():
 for key in ['operation','n','bytes','nodes','hashes','permutations','instructions','macro_count','macro_hashes','hash_trace_sha256']:
  assert row[key]==old[name][key],(name,key)
 assert row['cycles']<old[name]['cycles'],name
synthstate=json.loads((root/'build/synth/chain_atp_transposed_handoff/status.json').read_text());resources=synthstate['resources']
source_synth=json.loads((root/'build/synth/chain_atp_transposed_handoff/SOURCE.json').read_text())
for name in f.sources()+['rtl/executor/instructions.svh','sources.txt']:
 assert sha(root/name)==source_synth['files'][name]
for mode in ['stats_on','stats_off']:
 for name in ['slh_128f','xmss_h10','lms_h10']:
  row=synthview['cases'][name+'/'+mode];ref=cases[name+'/verify']
  for key in ['bytes','nodes','instructions','cycles','hash_trace_sha256']:assert row[key]==ref[key],(name,mode,key)
  if mode=='stats_off':assert row['stats']==0 and row['hashes']==0 and row['permutations']==0
image_identity=json.loads((archive/'IMAGES.json').read_text());assert image_identity['unchanged_from']=='12a61e05'
for name,val in image_identity['files'].items():assert sha(root/name)==val
# Freeze all production files together with the exact verification inputs/tools;
# raw simulation logs remain in build and are represented by per-case SHA256.
files=dict(identity)
for name in ['tb/tb_recipe.sv','scripts/check_recipes.py']+list(image_identity['files']):files[name]=sha(root/name)
with tarfile.open(archive/'rtl.tar.gz','w:gz') as tar:
 for name in sorted(files):tar.add(root/name,arcname=name,recursive=False)
source=dict(format='image_chain_atp_e_v1',candidate='E_transposed_handoff',working_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),uncommitted=True,hash_backend='shake',top='common',LANES=1,UNROLL=1,PROFILE_ENABLE=0,part='xc7a200tffg1156-3',clock_period_ns=10.0,routing_requested=False,program_rom_included=False,signature_store_included=False,files=files,rtl_snapshot_sha256=sha(archive/'rtl.tar.gz'),synthesis_source_sha256=sha(root/'build/synth/chain_atp_transposed_handoff/SOURCE.json'),synthesis_archive='../chain_atp_transposed_handoff_20261021',current_production_matches_measured_synthesis=True)
write(archive/'SOURCE.json',source)
for name,value in [('normal_28.json',dict(passed=True,cases=cases,source_sha256=identity)),('E_synthesis_view.json',synthview),('E_protocol.json',protocol)]:write(summaries/name,value)
recipe=json.loads((summaries/'E_recipe_evidence.json').read_text());assert recipe['status']=='passed' and len(recipe['checks'])==2
for path,val in recipe['source_sha256'].items():assert sha(root/path)==val
for check in recipe['checks']:assert check['result']['status']=='passed' and check['directed_handover_pairs']==14 and check['final_round_reset_replay']
validation=dict(format='image_chain_atp_e_validation_v1',status='passed',candidate='E_transposed_handoff',source_manifest_sha256=sha(archive/'SOURCE.json'),source_sha256=identity,normal_core_cases=28,normal_core_status='passed',synthesis_view_cases=6,synthesis_view_status='passed',protocol_cases=9,protocol_status='passed',recipe_cases_per_view=329,recipe_views=2,directed_handover_pairs_per_view=14,final_round_reset_replay=True,all_images_unchanged=True,all_normal_outputs_caches_hashes_permutations_instructions_and_task_traces_equal_baseline=True,routed_frequency_measured=False,h16_h15_complete_keygen_sign='not_run',h20_complete_keygen_sign='stopped_per_user',historical_manifest_note='Earlier import/stateful SOURCE and VALIDATION retain their historical binding; this SOURCE/VALIDATION proves current uncommitted E only.')
write(archive/'VALIDATION.json',validation)
# Retain failed candidates and their original frozen measurements.
data=json.loads((reports/'Chain_ATP_Optimization.json').read_text())
for row in data['candidates']:row['selection']='selected' if row['candidate']=='E_transposed_handoff' else 'rejected_area_or_atp_regression'
data.update(status='complete',selected_candidate='E_transposed_handoff',source_manifest_sha256=sha(archive/'SOURCE.json'),validation_manifest_sha256=sha(archive/'VALIDATION.json'),validation_summary=validation,validation=None,uncommitted=True)
image_area=4642.875;image_cycles=2800644;image_atp=image_area*image_cycles/100000
e_cycles=cases['slh_128f/sign']['cycles'];e_atp=resources['equivalent_slices']*e_cycles/100000
metrics=dict(lut=17577,ff=4734,equivalent_slices=4986.0,cycles=e_cycles,assumed_100mhz_latency_ms=e_cycles/100000,assumed_100mhz_atp_slice_ms=e_atp,relative_area_vs_branch_baseline=4986/4993-1,relative_cycles_vs_branch_baseline=e_cycles/2749196-1,relative_atp_vs_branch_baseline=e_atp/137267.35628-1,image_assumed_100mhz_atp_slice_ms=image_atp,relative_atp_vs_image=e_atp/image_atp-1,strict_ordering_image_gt_chain='not_met',timing_diagnostic=resources['timing_diagnostic'])
metrics['strict_ordering_target_met']=False
data['selected_metrics']=metrics
data['strict_ordering_target_met']=False
data.pop('validation',None)
# Root's isolated RTL structure trials use their own frozen SOURCE and reports.
roots=[]
for folder in archive.glob('root_*'):
 p=folder/'reports/Synthesis.json'
 if p.exists():
  x=json.loads(p.read_text());roots.append(dict(name=folder.name,resources=x.get('resources'),status='rejected_area_or_atp_regression',source_manifest_sha256=sha(folder/'SOURCE.json') if (folder/'SOURCE.json').exists() else None,clock_period_ns=10.0))
data['root_candidates']=roots;write(reports/'Chain_ATP_Optimization.json',data)
lines=['# image-chain 128f Sign ATP 优化（E，完成验证，未提交）','', '当前生产：未提交的E候选，基于 `12a61e05`。SHAKE、K1U1、单物理Hash通道、ABI3，12组program/descriptor与基线逐字不变；未改变端口、节点容量、算法和镜像。','', 'E把末轮完成和下一条已授权Hash的接受合并在同沿，删除每次Hash的一个空拍；CHAIN_RESULT写回与指令退休合并，另省每条非空CHAIN一拍。Hash完成不自行授权下一次Hash。固定帧采用image已有的逐源位互斥合并。','', '## 128f Sign 同口径结果','', 'common等效Slice=LUT/4+FF/8，不含程序ROM和签名缓存，BRAM/DSP均为0。下列100MHz是统一假定频率；未做布局布线。E综合WNS为−0.840ns，100MHz没有综合STA闭合证据，不能当作实板频率或布线ATP。','', '| 指标 | 修改前image-chain | 当前E | 净变化 |','|---|---:|---:|---:|', '| LUT | 17,609 | 17,577 | −32 |','| FF | 4,726 | 4,734 | +8 |','| 等效Slice | 4,993.000 | 4,986.000 | −0.1402% |','| Sign周期 | 2,749,196 | 2,638,099 | −4.0411% |','| 假定100MHz延迟/ms | 27.49196 | 26.38099 | −4.0411% |','| 假定100MHz ATP/Slice·ms | 137,267.35628 | 131,535.61614 | **−4.1756%** |','', '当前image的同频ATP为130,030.400115；E仍高1.1576%，因此尚未达到“image ATP > image-chain ATP”的预期顺序。宏粒度本身不保证ATP单调降低，未以理论排序替代测量。','', '## 候选取舍','', '| 候选 | LUT | FF | 等效Slice | 实测128f Sign周期 | 假定100MHz ATP | 取舍 |','|---|---:|---:|---:|---:|---:|---|']
for row in data['candidates']:
 r=row.get('resources'); assert r
 lines.append(f"| {row['candidate']} | {r['lut']:,.0f} | {r['ff']:,.0f} | {r['equivalent_slices']:,.3f} | {row['cycles_128f_sign']:,} | {row['assumed_100mhz_atp_slice_ms']:,.5f} | {'采用' if row['selection']=='selected' else '回撤/不采用'} |")
lines+=['','A/B帧级OR、D只转置帧、C1共享LMS C/I寄存器及其组合、两源operand XOR、read_node平行case、原优先帧、末轮前状态保留均已实测，不因逻辑推导看起来更小而保留。C1删382FF却增加2,091LUT，说明共享宽寄存器引入的选择与时序重构成本不能忽略。E之外的生产改动均未采用。','', 'ROOT还测试了rate输入OR、recipe/sponge层级边界和独立formatter边界，共5项失败/不优候选，冻结源码与报告位于本实验 `root_*` 子目录。formatter试验因全局并发上限临时排队暂停31.2秒，`CONCURRENCY_QUEUE.json`有记录；其elapsed不等同纯运行时间。B综合超过10分钟后仅延后分析，继续后台，最终结果完整归档。','', '## 验证','', '- 正常整核 **28/28通过**：六组SLH三操作、XMSS/LMS h10三操作、四组高树真实高度Verify。所有输出字节、签名缓存、Hash/置换数量、指令数量和逐Hash任务/结果轨迹与原独立参考默认向量一致；周期全部实测。','- E整核SYNTHESIS视图 **6/6通过**：SLH128f/XMSS h10/LMS h10 Verify各含stats_on、stats_off。输出、轨迹、周期和正常E一致；统计关闭时Hash/置换为0。100MHz综合的实际FF名称审计确认统计寄存器为0。','- E协议/拒绝 **9/9通过**：三算法分别执行输入停顿+CHAIN在途复位+重放、签名篡改拒绝、错误ABI拒绝。','- 配方每视图 **329/329通过**，两视图（PROFILE1正常、PROFILE0+SYNTHESIS），各覆盖14组同拍/停顿交接和最终轮复位重放，包括fixed→stream及fixed→非法请求的同拍边界。','- 所有证据均绑定本实验SOURCE；旧移植/Stateful_Extension全局SOURCE、VALIDATION仍绑定其历史版本，不用它们证明本次RTL。','- h16/h15完整Keygen/Sign未运行；h20完整Keygen/Sign继续按用户要求停止。本轮未启动任何布线。','', '| Sign | 原周期 | E周期 | Hash | 置换 |','|---|---:|---:|---:|---:|']
for name in ['slh_128f','xmss_h10','lms_h10']:
 k=name+'/sign';r=cases[k];lines.append(f"| {name} | {old[k]['cycles']:,} | {r['cycles']:,} | {r['hashes']:,} | {r['permutations']:,} |")
lines+=['', '当前源码校验见[SOURCE](../SOURCE.json)，完整验证状态见[VALIDATION](../VALIDATION.json)，归档清单见[ARTIFACTS](../ARTIFACTS.json)。E测量冻结源、分层面积、时序与综合日志位于 `../chain_atp_transposed_handoff_20261021/`；本实验另有当前生产和精确测试工具的 `rtl.tar.gz`。仿真明细日志仍在build，归档只保留源绑定摘要及日志校验。','', '本分支保持未提交，便于用户审阅；未移动分支引用。']
(reports/'Chain_ATP_Optimization.md').write_text('\n'.join(lines)+'\n')
write(archive/'ARTIFACTS.json',dict(source_manifest_sha256=sha(archive/'SOURCE.json'),validation_manifest_sha256=sha(archive/'VALIDATION.json'),routed=False,omitted_details=['sim','validation'],files={str(p.relative_to(archive)):sha(p) for p in archive.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json'}))
print('CHAIN_E_FINAL_PASS',len(cases),len(synthview['cases']),len(protocol['cases']),len(roots),e_atp)
