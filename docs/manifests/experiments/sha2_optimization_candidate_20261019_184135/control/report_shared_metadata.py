import argparse, hashlib, json, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()/'scripts'))
from report_sha2_optimization import hierarchy
import experiment_archive as archive

parser=argparse.ArgumentParser()
parser.add_argument('run', type=Path)
parser.add_argument('--decision', choices=['retained','discarded'], required=True)
parser.add_argument('--selected-run',type=Path)
args=parser.parse_args()
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
run=args.run.resolve(); meta=read(run/'SOURCE.json'); state=read(run/'status.json')
base=Path(meta['comparison_run']); old=read(base/'status.json')
assert state['complete'] and state['counts']['passed']==9 and state['previous_candidate_equivalence']['cycle_equal'] and state['previous_candidate_equivalence']['workload_equal']
assert all(v['status']=='passed' for v in state['synthesis'].values())
out=Path(meta['archive_directory']); local=Path(__file__).resolve().parent
for name in ['GATE.json','RECIPE_NORMAL.json','RECIPE_SYNTHESIS.json','ROBUSTNESS.json','ACVP_AND_SYNTHESIS.json','TRANSITION.json']:
 p=local/name; d=read(p)
 if name=='TRANSITION.json': assert d['passed'] and d['source_unchanged']
 if name in ('ROBUSTNESS.json','ACVP_AND_SYNTHESIS.json'):
  assert d['source_unchanged']
  if name=='ROBUSTNESS.json': assert d['passed']==d['total']==9
  else: assert d['passed'] and d['complete']
 if name.startswith('PRIMITIVE'):
  assert d['passed']==d['total'] and d['source_unchanged']
  assert all(meta['sha256'][n]==h for n,h in d['source_sha256'].items())
 source=d.get('rtl_sha256',d.get('source_sha256',d.get('source_after',{})))
 if source: assert all(meta['sha256'][n]==h for n,h in source.items())
 target=out/'prerequisites'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
shutil.copyfile(__file__,out/'control/report_shared_metadata.py')
for helper in ['run_robustness.py','run_acvp_synthesis.py','check_scalar_batch.py','tb_scalar_batch.sv']:
 shutil.copyfile(local/helper,out/'control'/helper)
rows=[]
for config,entry in state['synthesis'].items():
 prev=old['synthesis'][config]; a=entry['area']['equivalent_slice'];pa=prev['area']['equivalent_slice'];t=entry['timing']['data_path_ns'];pt=prev['timing']['data_path_ns']
 rows.append(dict(configuration=config,before=prev,after=entry,area_change_pct=100*(a/pa-1),path_change_pct=100*(t/pt-1),diagnostic_change_pct=100*(a*t/(pa*pt)-1),before_hierarchy=hierarchy(base/'synth'/config/'hierarchical.rpt'),after_hierarchy=hierarchy(run/'synth'/config/'hierarchical.rpt')))
current={n:sha(Path(n)) for n in meta['sha256'] if n.startswith('rtl/') or n=='sources.txt'}
expected=read(args.selected_run/'SOURCE.json') if args.selected_run else meta if args.decision=='retained' else read(base/'SOURCE.json')
assert all(expected['sha256'][n]==h for n,h in current.items())
report=dict(decision=args.decision,run=str(run),reference_run=str(base),scope='SHA2 shared scalar list arity and output length; unchanged cycles',source_manifest_sha256=sha(run/'SOURCE.json'),rows=rows,validation=state['previous_candidate_equivalence'],current_source=current,selected_run=str(args.selected_run) if args.selected_run else str(run if args.decision=='retained' else base))
lines=['# SHA2 标量元数据共享优化','',f'候选：{args.decision}。本轮比较基线为上一轮保留的固定窗口版本 `20261019_175821`，不把最早版本的大幅面积下降重复计为本轮收益。','',
'将仅标量请求使用的可变列表项数改为一个共享寄存器；批量列表保持固定arity=1，并通过scalar_slot区分，避免沿用前一标量请求的项数。不引入每槽Hash长度缓存。输出长度改为一个标量寄存器；批量结果长度固定不超过32字节，不读取标量长度决定是否继续MGF。减少逐槽输出长度银行及返回端的标签选择。SHA256原语、轮询仲裁、列表预取、格式化窗口和所有执行拍数均不变；没有P/U特化。','',
'共同核common、xc7a200tffg1156-3、Vivado 2025.2、100MHz、OOC、默认时序驱动，每进程2线程。等效Slice = LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP。未布线；综合时延不能作为实测最高频率。','',
'| 配置 | 原Slice | 候选Slice | 面积变化 | 原路径 ns | 候选路径 ns | 候选WNS ns | 原SHA256 LUT | 候选SHA256 LUT |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for r in rows:
 b=r['before'];a=r['after'];lines.append(f"| {r['configuration']} | {b['area']['equivalent_slice']:,.3f} | {a['area']['equivalent_slice']:,.3f} | {r['area_change_pct']:.3f}% | {b['timing']['data_path_ns']:.3f} | {a['timing']['data_path_ns']:.3f} | {a['timing']['wns_ns']:.3f} | {r['before_hierarchy']['sha256']['lut']} | {r['after_hierarchy']['sha256']['lut']} |")
for profile in ['slh_128f','xmss_h10','lms_h10']:
 lines+=['',f'## {profile} Sign','', '| 配置 | 实测周期 | 周期相同 | 100MHz假设时间 ms | 原ATP Slice·ms | 候选ATP Slice·ms | ATP变化 |','|---|---:|---|---:|---:|---:|---:|']
 for r in rows:
  c=r['configuration'];n=state['tests'][c+'/'+profile]['cycles'];p=old['tests'][c+'/'+profile]['cycles'];a=r['after']['area']['equivalent_slice'];b=r['before']['area']['equivalent_slice']
  lines.append(f'| {c} | {n:,} | {n==p} | {n/100000:.5f} | {b*p/100000:.3f} | {a*n/100000:.3f} | {100*(a*n/(b*p)-1):.3f}% |')
lines+=['','验证：P4U1普通与P12U1综合视图各345项配方，共690项，以及批配方验证通过。九项整核Sign全部通过，周期、Hash/压缩计数和向量与上一版本完全一致，完整输出和签名缓存逐字节核对；另有9项异常/停顿/复位回归、4项NIST ACVP完整签名及3项综合视图Sign。另有独立hashlib计算的专项测试：34/30/34字节标量摘要与批量MGF交替、67节点标量列表后接单节点批量列表、无复位重放和返回停顿，证明批量请求不受前一标量输出长度和列表项数影响。SHA256原语未改变，不重复原语验证。','',
'面积、时间和ATP均以未舍入数据比较。100MHz为统一假设频率，面积×周期×综合路径仅作诊断。原有双后端长回归不因本轮修改而停止；本轮不运行h20完整树。','',
'冻结RTL、源码校验、综合分层/时序报告和日志已归档。原始仿真日志留build运行目录；归档仅保存验证摘要。当前工作区与最终选择源码的对应关系保存在FINAL_SELECTION.json。','']
p=out/'reports'/('SHA2_Shared_Metadata_'+meta['run_id']);archive.atomic(p.with_suffix('.md'),'\n'.join(lines));archive.atomic(p.with_suffix('.json'),json.dumps(report,indent=2)+'\n')
archive.atomic(out/'FINAL_SELECTION.json',json.dumps(report,indent=2)+'\n')
a=read(out/'ARTIFACTS.json');a['sha256']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json' and not p.name.endswith('.tmp')};archive.atomic(out/'ARTIFACTS.json',json.dumps(a,indent=2)+'\n');archive.index()
print(p)
