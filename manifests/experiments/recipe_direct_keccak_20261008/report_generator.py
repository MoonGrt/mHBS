import csv,hashlib,json,shutil,subprocess
from pathlib import Path
root=Path.cwd();exp=root/'manifests/experiments/recipe_direct_keccak_20261008';cand=exp/'direct';work=root/'build/recipe_direct_keccak_20261008'
read=lambda p:json.loads(p.read_text())
measured=read(cand/'inputs.json')['source_sha256'];validated=read(exp/'validation_source/inputs.json')['source_sha256']
for name in (root/'manifests/v42_sources.txt').read_text().split():
 assert measured[name]==validated[name]==hashlib.sha256((root/name).read_bytes()).hexdigest(),name
base=read(exp/'baseline/results.json');rows=read(cand/'results.json');decision=read(cand/'decision.json');validation=read(cand/'validation.json');assert decision['accepted'] and decision['validated']
for p in (1,2,3,4):
 ref=read(cand/'simulation.json')[str(p)];replay=validation[f'P{p}_replay']
 assert replay['sign_cycles']-replay['wait_cycles']==ref['sign_cycles']
 golden=(cand/'simulation'/f'K1P{p}U1.actual.mem').read_text().split()
 actual=(cand/'simulation'/f'K1P{p}U1_replay.actual.mem').read_text().split()
 assert actual[-len(golden):]==golden and actual[-2*len(golden):-len(golden)]==golden
 assert actual[:-2*len(golden)]==golden[:len(actual)-2*len(golden)]
old={r['point']:r for r in base};combined=[]
for r in rows:
 b=old[r['point']];assert r['compute_cycles']==b['compute_cycles'] and r['total_cycles']==b['total_cycles'];assert (r['hashes'],r['permutations'])==(104937,105641)
 combined.append(dict(**r,baseline_lut=b['lut'],baseline_ff=b['ff'],baseline_slice=b['equivalent_slice'],baseline_atp=b['atp_slice_ms'],lut_delta=r['lut']-b['lut'],slice_delta=r['equivalent_slice']-b['equivalent_slice'],atp_change_percent=100*(r['atp_slice_ms']/b['atp_slice_ms']-1)))
# Supplemental default keygen and all six normal verify cases.
kgdir=root/'build/v4.2/external_job_message/recipe_direct_keccak_kg_20261008_v2'
vdir=root/'build/v4.2/external_job_message/recipe_direct_keccak_20261008_v2/verify'
kg=read(kgdir/'simulation.json');assert kg['cases']['slh_128f_keygen']['keygen_cycles']==29862
v=read(vdir/'results.json');expected={'slh_128f':84040,'slh_192f':118019,'slh_256f':123463,'slh_128s':29323,'slh_192s':42553,'slh_256s':62966}
for name,c in expected.items():assert v['profiles'][name]['normal']['cycles']==c
shutil.copytree(kgdir/'logs',exp/'default_keygen',dirs_exist_ok=True);shutil.copy2(kgdir/'simulation.json',exp/'default_keygen/results.json')
shutil.copytree(vdir,exp/'default_verify',ignore=shutil.ignore_patterns('obj'),dirs_exist_ok=True)
for name in ['contracts.log','rounds.log','basic_units_v2.log','candidate.log','verify_v2.log','keygen_v2.log']:shutil.copy2(work/name,exp/name)
# Keep preflight mistakes separate from the accepted measurements.
failed=exp/'preflight';failed.mkdir(exist_ok=True)
for name in ['units.log','basic_units.log','verify.log','keygen.log']:shutil.copy2(work/name,failed/name)
(failed/'README.md').write_text('Initial migration checks exposed two mechanical issues: `$error` was renamed with the local error signal, and the frozen padding reference permutation-count output was left connected to the DUT wire. Both were corrected; final RTL and migrated tests passed. The first basic-unit run stopped on its source-identity guard after the assertion-name correction. These logs are not accepted measurement evidence.\n')
# Full patch includes newly added test references. Historical evidence stays untouched.
patch=subprocess.check_output(['git','diff','HEAD','--','rtl','tb','scripts','manifests/v42_sources.txt','manifests/unified_sources.txt','docs/Architecture.md'],cwd=root)
new=subprocess.check_output(['git','ls-files','--others','--exclude-standard','tb','scripts'],cwd=root,text=True).splitlines()
for f in new:
 r=subprocess.run(['git','diff','--no-index','--','/dev/null',f],cwd=root,stdout=subprocess.PIPE);assert r.returncode in (0,1);patch+=r.stdout
(exp/'implementation.patch').write_bytes(patch)
best=min(rows,key=lambda r:r['atp_slice_ms']);before=min(base,key=lambda r:r['atp_slice_ms']);change=100*(best['atp_slice_ms']/before['atp_slice_ms']-1)
summary=dict(baseline_commit='76d8e565',frequency_mhz_assumed=150,clock_ns=6.666667,routed=False,scope='128f sign common core',structural_retention_required=True,baseline=base,final=combined,best_atp_change_percent=change,verification={'candidate':validation,'basic_units':read(exp/'basic_units/results.json'),'rounds':read(exp/'round_units/results.json'),'pipeline':read(cand/'unit_evidence/results.json'),'default_keygen':kg,'default_verify':v,'contract_tests':14},evidence=str(exp.relative_to(root)))
for dest in [exp/'report.json',root/'docs/v4.2/Recipe_Direct_Keccak.json']:dest.write_text(json.dumps(summary,indent=2)+'\n')
for dest in [exp/'report.csv',root/'docs/v4.2/Recipe_Direct_Keccak.csv']:
 with dest.open('w') as f:w=csv.DictWriter(f,fieldnames=combined[0]);w.writeheader();w.writerows(combined)
text=f'''# recipe lane 直接驱动 Keccak

基线提交 `76d8e565`，其全部生产 RTL SHA-256 与上一轮 `c3_batch_control` 测量一致。删除 `mhbs_compact_shake_context_lane.sv`，将吸收、状态写入、反馈、capture 和流水控制并入 `mhbs_recipe_lane`；直接展开 P×U 个 `mhbs_keccak`，保留多上下文链调度器。未新增包装模块、计算引擎或流水级，未重排控制状态。

固定配置下删除未启用的通用链模板、独立反馈构造及未消费的内部完成脉冲；反馈继续共用 `fast_block`。P1 保留原末轮完成时刻，P>1 保留 SHARED_STATE 语义。冻结旧实现只存在于 `tb/reference`，不参与生产综合。

## 综合与 ATP

仅 128f sign，共同核，器件 `xc7a200tffg1156-3`，`flatten_hierarchy=rebuilt`、`max_dsp=0`、统计关闭。约束 6.666667 ns，**150 MHz 为假定值，未经布局布线验证**。本轮未测真实频率。

| 配置 | LUT（含 LUTRAM） | FF | LUTRAM | BRAM36 | DSP | 等效 Slice | 计算周期 | 总周期 | Hash | 置换 | 时间 ms | ATP Slice·ms | 有效轮利用率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
'''
for r in rows:text+=f"| {r['point']} | {r['lut']:,.0f} | {r['ff']:,.0f} | {r['lutram']:,.0f} | {r['bram36']:g} | {r['dsp']:g} | {r['equivalent_slice']:,.3f} | {r['compute_cycles']:,} | {r['total_cycles']:,} | {r['hashes']:,} | {r['permutations']:,} | {r['time_ms']:.6f} | {r['atp_slice_ms']:,.3f} | {r['keccak_utilization']:.2%} |\n"
text+='\n| 配置 | 原 LUT / FF | 原等效 Slice | 原 ATP | LUT 变化 | Slice 变化 | ATP 变化 |\n|---|---:|---:|---:|---:|---:|---:|\n'
for r in combined:text+=f"| {r['point']} | {r['baseline_lut']:,.0f} / {r['baseline_ff']:,.0f} | {r['baseline_slice']:,.3f} | {r['baseline_atp']:,.3f} | {r['lut_delta']:+,.0f} | {r['slice_delta']:+,.3f} | {r['atp_change_percent']:+.3f}% |\n"
text+=f'''
最低 ATP：{before['atp_slice_ms']:,.3f} → **{best['atp_slice_ms']:,.3f}**（{best['point']}，变化 {change:+.3f}%）。按预定口径，结构重构通过功能和周期验证后保留，面积变化如上。

等效 Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP；LUT 已含 LUTRAM。时间(ms)=计算周期/150000；ATP=等效 Slice×时间。有效轮利用率=置换次数×24/(K×P×U×计算周期)，为有效轮吞吐比例，不是逐级实测占用率。面积不含外部 ROM 和签名存储。

## 验证

- 四组签名字节与软件向量一致；计算/总周期与冻结测量完全一致，Hash/置换均为 104937/105641。
- 四组统计关闭、停顿、复位重放、尾部噪声、连续请求；扣除输入等待后计算周期不变。共同核提取等价、两类异常退出通过。
- 默认 K2P1U2 sign=729983、keygen=29862 个计算周期；K2P4U1 sign=486328。默认六参数 Verify 正常用例输出及周期均与既有表一致（本轮不是完整 130 项 Verify 扩展回归）。
- 16 项基础单元、12 组迁移后的 recipe/交错流水单元、4 组全轮号/随机轮函数检查、14 项 Python 契约测试通过。覆盖 16/24/32 字节节点、普通/compact 链、capture、不同链长/零步、背压、复位取消与 tag 复用，以及 135/136/137 字节填充和长列表多块吸收。
- 流水测试从 recipe batch 接口发任务；每级通过冻结轮函数检查组合输出、状态、tag 和有效位。普通 recipe/填充逐拍对照冻结旧实现，未新增生产测试端口。
- 四组综合统计寄存器裁剪检查均通过。

## 证据

[独立实验目录](../../manifests/experiments/recipe_direct_keccak_20261008/) 包含冻结基线、综合快照、完整补丁、日志、分层报告及 CSV/JSON。

综合使用 `direct/source_snapshot.tar.gz`。迁移的填充测试修复一处参考输出接线后，最终验证源码另存 `validation_source/source_snapshot.tar.gz`；两份快照的全部生产 RTL 完全相同，差异及原因见 `validation_source/changes_from_measurement.json`。初次迁移失败日志单列 `preflight/`，不作为通过证据。

'''
for r in rows:
 point=r['point'];text+=f'- [{point} 分层面积报告](../../manifests/experiments/recipe_direct_keccak_20261008/direct/{point}/core_hierarchical.rpt)\n'
text+='\n未提交、未推送；历史结果和文件名保持原样。\n'
(root/'docs/v4.2/Recipe_Direct_Keccak.md').write_text(text)
(exp/'report.md').write_text(text.replace('../../manifests/experiments/recipe_direct_keccak_20261008/','./'))
# Content evidence index after all delivered files exist.
(exp/'evidence_sha256.json').write_text(json.dumps({str(p.relative_to(exp)):hashlib.sha256(p.read_bytes()).hexdigest() for p in exp.rglob('*') if p.is_file() and p.name!='evidence_sha256.json' and p.suffix!='.dcp'},indent=2)+'\n')
print('DELIVERY_PASS',best['point'],best['atp_slice_ms'],change)
