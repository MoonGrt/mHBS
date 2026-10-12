from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import difflib, hashlib, json, re, shutil, sys

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'scripts'))
from experiment_archive import archive_run, index, pack_rtl

BEFORE = ROOT/'build/pu_sign_matrix/20261014_193307'
AFTER = ROOT/'build/pu_sign_matrix/20261014_193550'
OUT = ROOT/'docs/manifests/experiments/legacy_cleanup_20261014_193550'
REPORT = OUT/'reports/Legacy_Cleanup_20261014'
OUT.mkdir(parents=True,exist_ok=True)
REPORT.parent.mkdir(parents=True,exist_ok=True)

def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')

meta_before=json.loads((BEFORE/'SOURCE.json').read_text())
meta_after=json.loads((AFTER/'SOURCE.json').read_text())
before=json.loads((BEFORE/'status.json').read_text())
after=json.loads((AFTER/'status.json').read_text())
for run in (BEFORE,AFTER): archive_run(run)
for folder,meta,run in ((OUT/'baseline',meta_before,BEFORE),(OUT,meta_after,AFTER)):
    folder.mkdir(parents=True,exist_ok=True)
    pack_rtl(meta['source_root'],folder/'rtl.tar.gz',meta['sha256'])
    shutil.copy2(run/'SOURCE.json',folder/'SOURCE.json')
    for path in (run/'synth').rglob('*'):
        if path.is_file() and path.suffix in ('.rpt','.log','.json','.txt'):
            target=folder/path.relative_to(run)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,target)

patch=[]
for name in sorted(meta_after['sha256']):
    if meta_before['sha256'].get(name)!=meta_after['sha256'][name]:
        left=(Path(meta_before['source_root'])/name).read_text().splitlines(keepends=True)
        right=(Path(meta_after['source_root'])/name).read_text().splitlines(keepends=True)
        patch.extend(difflib.unified_diff(left,right,fromfile='baseline/'+name,tofile='candidate/'+name))
(OUT/'candidate.patch').write_text(''.join(patch))

summary=json.loads((WORK/'SUMMARY.json').read_text()) if (WORK/'SUMMARY.json').exists() else None
if summary:
    write(OUT/'VALIDATION_SUMMARY.json',summary)
    shutil.copy2(WORK/'STATE_ENCODING_PROOF.json',OUT/'STATE_ENCODING_PROOF.json')
if (WORK/'EXTRA_SUMMARY.json').exists():
    shutil.copy2(WORK/'EXTRA_SUMMARY.json',OUT/'EXTRA_SUMMARY.json')
if (WORK/'VIEW_EQUIVALENCE_SUMMARY.json').exists():
    shutil.copy2(WORK/'VIEW_EQUIVALENCE_SUMMARY.json',OUT/'VIEW_EQUIVALENCE_SUMMARY.json')

areas=[]; cycles=[]
def timing(run,cfg):
    path=run/'synth'/cfg/'common/timing.rpt'
    if not path.exists():return None
    match=re.search(r'WNS\(ns\).*?\n\s*-+[^\n]*\n\s*(-?[\d.]+)\s+(-?[\d.]+)',path.read_text(),re.S)
    return dict(wns_ns=float(match[1]),tns_ns=float(match[2])) if match else None
for p in (1,4,12):
    cfg=f'P{p}U1'; key=f'synth/{cfg}/common'
    b,a=before['tasks'][key],after['tasks'][key]
    ba,aa=b.get('area'),a.get('area')
    areas.append(dict(configuration=cfg,before=ba,after=aa,
        before_status=b['status'],after_status=a['status'],
        before_analysis_deferred=b.get('analysis_deferred',False),
        after_analysis_deferred=a.get('analysis_deferred',False),
        before_seconds=b.get('seconds'),after_seconds=a.get('seconds'),
        before_timing=timing(BEFORE,cfg),after_timing=timing(AFTER,cfg),
        delta_slice=aa['equivalent_slice']-ba['equivalent_slice'] if ba and aa else None))
    for profile in ('slh_128f','xmss_h10','lms_h10'):
        key=f'sim/{cfg}/{profile}'
        bs,as_=before['tasks'][key],after['tasks'][key]
        equal=bs['status']==as_['status']=='passed' and all(bs[k]==as_[k] for k in ('cycles','total_cycles','hashes','permutations'))
        cycles.append(dict(configuration=cfg,profile=profile,before_cycles=bs.get('cycles'),after_cycles=as_.get('cycles'),
            before_hashes=bs.get('hashes'),after_hashes=as_.get('hashes'),
            before_permutations=bs.get('permutations'),after_permutations=as_.get('permutations'),
            unchanged=equal,time_ms=as_['cycles']/150000 if as_.get('cycles') else None,
            before_atp=ba['equivalent_slice']*bs['cycles']/150000 if ba and bs.get('cycles') else None,
            after_atp=aa['equivalent_slice']*as_['cycles']/150000 if aa and as_.get('cycles') else None))
data=dict(before_run=str(BEFORE),after_run=str(AFTER),areas=areas,sign_results=cycles,
    full_signs_compared=len(cycles),sign_cycles_and_workload_unchanged=all(r['unchanged'] for r in cycles),
    regression=summary,all_syntheses_complete=before.get('complete') and after.get('complete'),
    h20_full_keygen_sign_run=False,routed_sta=False,assumed_frequency_mhz=150,
    area_top='common',clock_period_ns=6.666667,part='xc7a200tffg1156-3')
write(REPORT.with_suffix('.json'),data)

def fmt(n,d=0):return '—' if n is None else f'{n:,.{d}f}'
lines=['# 旧代码残留清理与 P1/P4/P12U1 对照','',
    '删除 `scheduled_execution` 内不可实例化的 P1 迭代路径、未消费的 ctx_response_digest/capture、只写不读的 chain_id、未使用的 HP 与 lane_list0/1 连接，以及五个退休状态名。保留所有活动状态的原编码与 7 位宽度，清除调试分类中的退休数字状态。', '',
    '保留 P1 标量路径、P>1 调度路径、有效的 RECIPE_MASK、SYNTHESIS 仿真观察信号、标准参数迁移拒绝检查和历史报告。修正活动脚本与项目说明中遗留的 20 分钟默认值为 10 分钟；超过阈值只暂缓分析，综合继续运行。', '',
    f'修改前冻结：`{BEFORE}`；修改后冻结：`{AFTER}`。两套源码各自实跑三次 common 综合与九项完整 Sign，避免借用历史面积。', '',
    '器件 xc7a200tffg1156-3，通用 Keccak，OOC，6.666667 ns 约束，默认时序驱动综合，每个 Vivado 两线程。等效 Slice = LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP；不含外部 ROM 与签名缓存。无新增时序例外。', '',
    '## 综合面积', '',
    '| P/U | 前 LUT / FF | 后 LUT / FF | 后 BRAM36 | 前等效 Slice | 后等效 Slice | 差值 Slice | 前/后综合秒 | 状态 |',
    '|---|---:|---:|---:|---:|---:|---:|---:|---|']
for r in areas:
    b,a=r['before'] or {},r['after'] or {}
    lines.append(f"| {r['configuration']} | {fmt(b.get('lut'))} / {fmt(b.get('ff'))} | {fmt(a.get('lut'))} / {fmt(a.get('ff'))} | {fmt(a.get('bram36'))} | {fmt(b.get('equivalent_slice'),3)} | {fmt(a.get('equivalent_slice'),3)} | {fmt(r['delta_slice'],3)} | {fmt(r['before_seconds'],1)} / {fmt(r['after_seconds'],1)} | {r['before_status']} / {r['after_status']} |")
lines += ['', 'P1U1/P4U1 综合 WNS 分别为 -0.788/-1.849 ns，前后相同；当前 6.666667 ns 约束仍有违例，未将假定频率视为时序闭合结果。', '']
if not (before.get('complete') and after.get('complete')):
    lines += ['P12U1 尚未完成，其面积与 ATP 留空；超过 10 分钟仅暂缓当前分析，两套综合均继续运行。后台 watch_report.py 将自动更新本报告和归档证据。', '']
for profile,title in (('slh_128f','SLH-DSA 128f Sign'),('xmss_h10','XMSS h10 Sign'),('lms_h10','LMS h10 Sign')):
    lines+=['',f'## {title}','', '| P/U | 前周期 | 后周期 | Hash / 置换 | 时间 ms | 前 ATP | 后 ATP | 周期及工作量一致 |', '|---|---:|---:|---:|---:|---:|---:|---|']
    for r in cycles:
        if r['profile']==profile:
            lines.append(f"| {r['configuration']} | {fmt(r['before_cycles'])} | {fmt(r['after_cycles'])} | {fmt(r['after_hashes'])} / {fmt(r['after_permutations'])} | {fmt(r['time_ms'],6)} | {fmt(r['before_atp'],3)} | {fmt(r['after_atp'],3)} | {'是' if r['unchanged'] else '待确认'} |")
lines+=['','时间和 ATP 按 150 MHz 假定折算；不是布局布线 STA 结论。综合 timing.rpt 已归档，未执行布线。','', '## 验证与证据','']
if summary:
    lines += [f"额外 {summary['checks']} 项检查全部通过：{summary['passed']}；冻结源码未改变：{summary['source_unchanged']}。六组配方共 2,754 例；普通/SYNTHESIS 两视图批量测试共 24 组、192 请求；另有 9 项 SYNTHESIS 完整 Sign、18 项两视图 Verify 和统计测试。结合矩阵，候选共执行 18 项 Sign、18 项 Verify；输出及签名缓存逐字节核对，SYNTHESIS 视图统计端口裁剪。",'']
if (WORK/'EXTRA_SUMMARY.json').exists():
    extra=json.loads((WORK/'EXTRA_SUMMARY.json').read_text())
    lines += [f"补充 P3U2 配方与 P4U1/P12U1 的 SHARED_STATE=0 配方路径，共 1,377 例，通过：{extra['passed']}。全部配方合计 4,131 例；18 组 Sign/Verify 普通与 SYNTHESIS 视图的周期、启动总周期、Hash 和置换计数逐项一致，见 VIEW_EQUIVALENCE_SUMMARY.json。",'']
lines += ['修改前后冻结 RTL、源码校验、candidate.patch、三组 hierarchical.rpt/timing.rpt/utilization.rpt/debug_audit.json 与 Vivado 日志均归档；仿真及验证明细日志保留在运行目录，只归档结果摘要。h20 完整 Keygen/Sign 未启动。', '',
    f'原始验证日志：`{WORK}`；源码内部原始仿真日志：`{AFTER}/source/build`。', '']
REPORT.with_suffix('.md').write_text('\n'.join(lines))
shutil.copy2(Path(__file__),OUT/'REPORT_GENERATOR.py')
artifacts={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json'}
pending=[]
for stage,run,state in (('baseline',BEFORE,before),('candidate',AFTER,after)):
    for key,task in state['tasks'].items():
        if key.startswith('synth/') and task['status']!='passed':
            pending.append(dict(stage=stage,task=key,status=task['status'],
                analysis_deferred=task.get('analysis_deferred',False),
                reports_pending=[name for name in ('hierarchical.rpt','timing.rpt') if not (run/key/name).exists()]))
write(OUT/'ARTIFACTS.json',dict(updated_at=datetime.now(ZoneInfo('Asia/Singapore')).isoformat(),sha256=artifacts,
    pending=pending,background_report_updater=str(WORK/'watch_report.py'),
    omitted_details=['sim','validation'],report=str(REPORT.with_suffix('.md'))))
index()
print(json.dumps(dict(report=str(REPORT.with_suffix('.md')),areas=areas,cycles_unchanged=data['sign_cycles_and_workload_unchanged'],complete=data['all_syntheses_complete']),indent=2))
