from pathlib import Path
import difflib,hashlib,json,sys
sys.path.insert(0,str(Path.cwd()/'scripts'))
import experiment_archive as archive
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
root=Path('build/sha2_optimization');base=root/'candidate_20261019_175821';bm=read(base/'SOURCE.json');bs=read(base/'status.json')
trials=[('182117','轮内进位保存加法树'),('182609','Hash长度预登记'),('183037','长度预登记＋列表预取捷径'),('183548','长度预登记＋标量输出长度共享'),('184135','仅共享标量列表项数／输出长度')]
rows=[]
for stamp,name in trials:
 r=root/f'candidate_20261019_{stamp}';m=read(r/'SOURCE.json');s=read(r/'status.json');out=Path(m['archive_directory'])
 assert s['complete'] and s['counts']['passed']==9 and s['previous_candidate_equivalence']['cycle_equal'] and s['previous_candidate_equivalence']['workload_equal']
 assert all(x['status']=='passed' for x in s['synthesis'].values())
 changes=[]
 for n,h in m['sha256'].items():
  if n.startswith('rtl/') and h!=bm['sha256'][n]:
   changes+=list(difflib.unified_diff((base/'source'/n).read_text().splitlines(True),(r/'source'/n).read_text().splitlines(True),fromfile='baseline/'+n,tofile='candidate/'+n))
 archive.atomic(out/'candidate.patch',''.join(changes))
 best={}
 for profile in ['slh_128f','xmss_h10','lms_h10']:
  def optimum(state):
   return min((state['synthesis'][c]['area']['equivalent_slice']*state['tests'][c+'/'+profile]['cycles']/100000,c) for c in ['P1U1','P4U1','P12U1'])
  old,oldcfg=optimum(bs);new,newcfg=optimum(s)
  best[profile]=dict(old_atp=old,candidate_atp=new,old_configuration=oldcfg,candidate_configuration=newcfg,change_pct=100*(new/old-1))
 rows.append(dict(name=name,run=str(r),archive=str(out),decision='discarded',measurements=s['synthesis'],best_assumed_atp=best,cycles_unchanged=True))
current={n:sha(Path(n)) for n in bm['sha256'] if n.startswith('rtl/') or n=='sources.txt'}
assert all(h==bm['sha256'][n] for n,h in current.items())
out=Path(read((root/'candidate_20261019_184135')/'SOURCE.json')['archive_directory'])
lines=['# SHA2 后续五候选对照与最终选择','','本轮未找到三个算法最佳固定频率ATP同时不回退的组合，当前RTL已恢复到本轮起点（上一轮保留的 `20261019_175821`）。全部五候选冻结源码与测量证据保留，未将综合路径改善等同于布线频率改善。','',
'五候选合计完成45项完整Sign、15次common综合；全部Sign输出、签名缓存、Hash/压缩计数及周期匹配起点。每候选统一测试P1U1/P4U1/P12U1以及SLH128f、XMSS h10、LMS h10。综合任务完成不代表时序闭合。','',
'器件xc7a200tffg1156-3，Vivado2025.2，100MHz/OOC/默认时序驱动，每进程2线程，无新增时序例外，无布局布线。等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。ATP按假设100MHz计算，未舍入比较保存在JSON。','',
'| 候选 | P1U1 Slice | P4U1 Slice | P12U1 Slice | 选择 |','|---|---:|---:|---:|---|']
configs=['P1U1','P4U1','P12U1']
lines.append('| 本轮起点 | '+' | '.join(f"{bs['synthesis'][c]['area']['equivalent_slice']:,.3f}" for c in configs)+' | 保留 |')
for x in rows:lines.append('| '+x['name']+' | '+' | '.join(f"{x['measurements'][c]['area']['equivalent_slice']:,.3f}" for c in configs)+' | 未采用 |')
lines+=['','| 候选 | P1U1综合路径 ns | P4U1综合路径 ns | P12U1综合路径 ns |','|---|---:|---:|---:|']
lines.append('| 本轮起点 | '+' | '.join(f"{bs['synthesis'][c]['timing']['data_path_ns']:.3f}" for c in configs)+' |')
for x in rows:lines.append('| '+x['name']+' | '+' | '.join(f"{x['measurements'][c]['timing']['data_path_ns']:.3f}" for c in configs)+' |')
for profile in ['slh_128f','xmss_h10','lms_h10']:
 lines+=['',f'## {profile} 最佳假设ATP','', '| 候选 | 最佳配置 | 起点ATP Slice·ms | 候选ATP Slice·ms | 变化 |','|---|---|---:|---:|---:|']
 for x in rows:
  a=x['best_assumed_atp'][profile];lines.append(f"| {x['name']} | {a['candidate_configuration']} | {a['old_atp']:.3f} | {a['candidate_atp']:.3f} | {a['change_pct']:+.3f}% |")
lines+=['','各阶段的关键结果：','','- 进位保存加法树通过全部30个合法P/U原语测试，但共同核面积未获得整体收益。','- 长度预登记缩短了P12U1控制路径，却增加了该配置面积。列表预取捷径进一步改善路径，但扩大面积回退。','- 标量长度／列表项数共享通过跨标量与批量请求的独立hashlib专项测试，功能上安全；FF减少未稳定转化为LUT或共同核面积下降。','- “长度预登记＋标量输出长度共享”将P12U1路径从10.935ns降至10.154ns，同时面积增加约2.14%；它是后续显式布线比较可参考的候选，本轮没有据综合时延认定实际ATP获益。','',
'验证摘要和限制：长度相关四候选均有官方ACVP、综合视图Sign以及停顿/截断/篡改/在途复位回归；每轮均绑定自己的源码SHA。最后两候选增加标量/批量共享安全测试，最后一轮还覆盖67节点标量列表后跟单节点批量列表。先前完整大树回归与本轮证据分别保存；本轮没有启动h20完整树，也没有终止旧后台任务。','',
'每个候选的主报告包含独立面积表与三个算法的周期、时间、ATP表。冻结RTL、候选补丁、源码校验、分层/时序报告和综合日志分别归档；原始仿真日志留运行目录。','', '## 实验证据','']
for x in rows:
 ap=Path(x['archive']);stamp=ap.name.split('candidate_')[1];lines.append(f"- {x['name']}：[测量报告](../../{ap.name}/reports/SHA2_Optimization_{stamp}.md)，`{x['run']}`。")
lines+=['',f"当前recipe SHA256：`{current['rtl/hash/sha2-recipe.sv']}`；SHA256原语：`{current['rtl/hash/sha256.sv']}`。",'']
prefix=out/'reports/SHA2_Five_Candidate_Review_20261019';archive.atomic(prefix.with_suffix('.md'),'\n'.join(lines));data=dict(retained_run=str(base),current_source=current,total_sign_tests=45,total_synthesis_runs=15,candidates=rows);archive.atomic(prefix.with_suffix('.json'),json.dumps(data,indent=2)+'\n');archive.copy_changed(Path(__file__),out/'control/review_all.py')
for x in rows:
 ap=Path(x['archive']);a=read(ap/'ARTIFACTS.json');a['sha256']={str(p.relative_to(ap)):sha(p) for p in ap.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json' and not p.name.endswith('.tmp')};archive.atomic(ap/'ARTIFACTS.json',json.dumps(a,indent=2)+'\n')
archive.index();print(prefix.with_suffix('.md'))
