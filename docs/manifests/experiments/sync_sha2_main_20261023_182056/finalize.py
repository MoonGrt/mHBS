from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib,json,subprocess,shutil,re,tarfile

RUN=Path(__file__).resolve().parent
ISO=RUN.parents[2]
SOURCE=RUN/'source'
TARGET=Path('/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS')
TS=RUN/'target_source'
ARCHIVE=ISO/'docs/manifests/experiments/sync_sha2_main_20261023_182056'
REL=ARCHIVE.relative_to(ISO)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
state=json.loads((RUN/'INITIAL_STATE.json').read_text())
target_validation=json.loads((RUN/'TARGET_VALIDATION.json').read_text())
assert target_validation['complete'] and target_validation['passed']
assert not Path('/proc/3162571').exists()
assert not Path('/proc/3244282').exists()
before=json.loads((RUN/'BEFORE.json').read_text())
target_before=json.loads((RUN/'TARGET_BEFORE.json').read_text())
assert subprocess.check_output(['git','branch','--show-current'],cwd=TARGET,text=True).strip()=='ablation'
assert subprocess.check_output(['git','rev-parse','main'],cwd=TARGET,text=True).strip()==before['upstream_commit']
initial_source=json.loads((RUN/'SOURCE.json').read_text())
assert all(sha(SOURCE/f)==h for f,h in initial_source.items())
target_source=json.loads((RUN/'TARGET_SOURCE.json').read_text())
assert all(sha(TS/f)==h and sha(TARGET/f)==h for f,h in target_source.items())
for f,h in target_before['all_rtl'].items():
    if f not in target_before['files']:assert sha(TARGET/f)==h
for design in ('i','c','t'):
    for file in ('sha2-recipe.sv','sha256.sv'):
        expected=before['upstream_inputs']['rtl/hash/'+file]
        assert sha(TARGET/f'rtl/{design}/hash/{file}')==expected
assert state['complete'] and state['jobs']['core_t']['status']=='failed'
assert all(v['status']=='passed' for n,v in state['jobs'].items() if n!='core_t')
retries=json.loads((RUN/'RETRY.json').read_text());assert all(x['returncode']==0 for x in retries)
pattern=re.compile(r'STATEFUL_PASS P(\d+)U(\d+) op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+) tamper=0 logical_permutations=(\d+)')
def extract(path,design,backend,case=None):
    result=[];trace=macro=None
    for line in Path(path).read_text(errors='replace').splitlines():
        if line.startswith('COMMAND '):
            command=json.loads(line[8:])
            if len(command)>3 and command[1]=='scripts/simulate_fast.sh':case=command[2:4]
        elif line.startswith('HASH_TRACE_METRICS '):trace=json.loads(line.split(' ',1)[1])
        elif line.startswith('MACRO_METRICS '):macro=json.loads(line.split(' ',1)[1])
        elif line.startswith('STATEFUL_PASS '):
            match=pattern.fullmatch(line.split(' seconds=')[0]);assert match and case
            p,u,op,cy,total,h,b,l=map(int,match.groups())
            result.append(dict(design=design,backend=backend,profile=case[0],operation=case[1],pipeline=p,unroll=u,
                cycles=cy,total_cycles=total,hashes=h,actual_compressions=b,logical_compressions=l,
                primitive_trace=trace,macro_metrics=macro,raw_log=str(path),passed=True))
    return result
records=[]
for d in ('i','c','t'):
    rows=extract(RUN/'logs'/f'core_{d}.log',d,'sha2');assert len(rows)==(10 if d=='t' else 12);records+=rows
for retry in retries:records+=extract(retry['log'],'t','sha2',(retry['profile'],'verify'))
assert len(records)==36
checks=[]
for profile,op in sorted({(r['profile'],r['operation']) for r in records}):
    rows=[r for r in records if r['profile']==profile and r['operation']==op];assert len(rows)==3
    assert rows[0]['primitive_trace']==rows[1]['primitive_trace']==rows[2]['primitive_trace'],(profile,op)
    checks.append(dict(profile=profile,operation=op,passed=True,trace=rows[0]['primitive_trace']))
current=[]
for record in target_validation['records']:
    row=extract(record['log'],'c',record['backend'],(record['profile'],'sign'))[0]
    row['synthesis']=record['synthesis'];current.append(row)
    ref=next(r for r in records if r['design']=='c' and r['profile']==row['profile'] and r['operation']=='sign') if row['backend']=='sha2' else extract(RUN/'logs/shake_c.log','c','shake')[0]
    for k in ('cycles','hashes','actual_compressions','logical_compressions','primitive_trace','macro_metrics'):assert row[k]==ref[k],(row['profile'],k)
shake=[]
for d,expected in [('i',5825429),('c',2958730),('t',2614610)]:
    row=extract(RUN/'logs'/f'shake_{d}.log',d,'shake')[0];assert row['cycles']==expected;shake.append(row)
old={'i':18181762,'c':15409870,'t':15065766};targets=[]
for d in ('i','c','t'):
    row=next(r for r in records if r['design']==d and r['profile']=='slh_128f' and r['operation']=='sign')
    targets.append(dict(design=d,old_cycles=old[d],cycles=row['cycles'],change_pct=(row['cycles']/old[d]-1)*100,
        hashes=row['hashes'],actual_compressions=row['actual_compressions'],logical_compressions=row['logical_compressions'],area=None,atp=None))
# i/t tested production inputs are byte-identical to the current worktree.
for design in ('i','t'):
    for path in (TS/'rtl'/design).rglob('*'):
        if path.is_file():assert sha(path)==sha(SOURCE/path.relative_to(TS))
report=dict(schema='mhbs.ablation.sha2_main_sync.v1',complete=True,passed=True,
    updated_at=datetime.now(ZoneInfo('Asia/Singapore')).isoformat(),upstream_commit=before['upstream_commit'],
    target_branch='ablation',target_root=str(TARGET),isolated_root=str(ISO),main_ref_unchanged=True,
    production_inputs_verified=True,synthesis_started=False,routing_started=False,report_updater_exited=True,
    targets=targets,isolated_core_cases=records,current_c_sign_compatibility=current,shake_compatibility=shake,
    cross_design_trace_checks=checks,validation_groups=state['jobs'],
    fixture_retry=dict(resolved=True,reason='Missing t h20 Verify fixture directories, no RTL failure',records=retries),
    static_rom=json.loads((RUN/'static_rom/VALIDATION_SUMMARY.json').read_text()),
    source_scope='Current i/t RTL identical to isolated full regressions; current c original executor/SHAKE retained and all three Sign cases plus SHAKE/SYNTHESIS Sign rechecked.',
    area_status='Not measured for synchronized RTL; previous area and ATP historical only',
    branch_observation='Primary worktree externally changed from main to ablation at18:27:04; no checkout or commit performed by this task. Applied sync to clean ablation paths only.')
(RUN/'FINAL.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
(ARCHIVE/'reports/SHA2_Main_Sync_20261023.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
lines=['# main SHA2行为修正同步到i／c／t','',f"完成时间：{report['updated_at']}",'',
    '已将main `a4a09e6f6ef901585e63aa8f37175b4931fad1cf` 的SHA2配方及SHA256通道同步到当前ablation分支的三种实现；六个模块文件与上游逐字节一致。未执行切分支或提交操作，main分支引用保持原值。',
    '任务先在隔离工作树验证；期间主工作区自行切到ablation，随后同步到当前分支。只写入SHA2模块、相关测试适配和缺失的Verify输入；其他生产RTL保持当前分支原样。','',
    '## 同步内容','',
    '- SLH：缓存PK.seed低128位加48字节零的原始SHA256前缀链值。',
    '- XMSS：缓存toByte(3,32)||PK.seed全256位，仅用于KEY／MASK0／MASK1；其他PRF、FINAL保持各自输入。',
    '- 同步种子与家族匹配、并发冷填充屏障、复位失效，以及配套固定块装配、链反馈和SHA256数据通道。',
    '- i仍逐次程序HASH，c使用CHAIN，t使用CHAIN／TREE；指令、程序／模板／描述符和控制粒度保持原样。',
    '- 模型／向量meta保留逻辑块数；统计和测试改为核对实际压缩数。trace使用压缩器真实输入握手，覆盖replay。',
    '- 隔离c的执行器／SHAKE面积改动保留在隔离工作树，未顺带带入当前ablation。旧SHA2移位装配／单槽CV直连由上游配套架构替代。','',
    '## SHA2-128f Sign：P1U1实测','',
    '| 实现 | 历史周期 | 同步后周期 | 变化 | 完整Hash | 实际压缩 | 逻辑压缩 |',
    '|---|---:|---:|---:|---:|---:|---:|']
for r in targets:lines.append(f"| {r['design']} | {r['old_cycles']:,} | **{r['cycles']:,}** | {r['change_pct']:.2f}% | {r['hashes']:,} | {r['actual_compressions']:,} | {r['logical_compressions']:,} |")
lines += ['', '三者实际压缩输入及完整Hash结果的多重集sum256、xor256指纹完全一致，工作量相同，均从复位后冷缓存开始。当前c的原执行器版本与隔离面积优化版本在本次补验的周期／输出／计数／轨迹也完全一致。','',
    '## 回归结果','',
    '- 60组镜像重新生成比对通过，ROM格式及内容不变，不生成完整h20树。',
    '- 隔离i/c/t各执行SLH128f、XMSS h10、LMS h10完整Keygen／Sign／Verify，共27项；逐字节检查输出、公钥、签名缓存，并严格核对Hash与实际压缩。',
    '- 隔离三者各执行SLH128s Verify、XMSS h20 Verify、LMS h20 Verify，共9项；补齐下述缺失输入后，正常整核36/36通过。12种算法／操作的跨设计压缩／Hash指纹全部一致。',
    '- 当前ablation的i/t生产RTL与上述受验RTL逐字节一致。当前c保留其原执行器与SHAKE实现，额外实跑三算法完整Sign、SHAKE128f Sign及SYNTHESIS完整SHA2-128f Sign，5/5通过；周期、字节、工作量及指纹与隔离结果相同。',
    '- 各设计345项SHA2配方，共1035项通过；SHA256原语181向量通过，覆盖停顿和复位重放。',
    '- 后端缓存测试P1U1、P4U1及P1U1 SYNTHESIS视图通过；每视图29项标量序列及6组批次，覆盖冷／热缓存、种子高低半变化、家族切换、并发填充、返回停顿、列表、HMAC／MGF1及复位。P4仅为独立后端覆盖，整核仍为K1U1。',
    '- c的top内置signature保存及SYNTHESIS视图通过。宏视图功能通过不等同新综合网表审计。',
    '- SHAKE128f Sign周期保持i=5,825,429、c=2,958,730、t=2,614,610。h20 Keygen／Sign始终未运行。','',
    '## 测试输入缺项与证据范围','',
    '首轮t在完成10项后，因缺少xmss_h20／lms_h20 Verify目录停止。复用已经通过i/c核验的标准Verify输入，由prepare_vector接入t自己的ROM，两项补测均通过。原缺项记录保留在initial_validation_summary.json，补充输入来源／校验和与结果单独归档；未修改历史报告。',
    '主工作区18:27:04由main切至ablation，属验证期间观察到的外部切换。本任务没有执行checkout，也没有更改main提交。当前分支同步前现场保存在target_before_source.tar.gz及TARGET_BEFORE.json。','',
    '## 面积与ATP','',
    '本轮仅同步与功能回归，未启动综合、布线或频率搜索。旧面积和ATP不代表同步后RTL，新面积／闭合频率／ATP留空。今后比较三种控制粒度应采用本次共同SHA2后端重新测量。','',
    '## 归档与复现','',
    'rtl.tar.gz及CURRENT_SOURCE.json对应当前ablation源码；isolated_rtl.tar.gz及SOURCE.json对应最初完整隔离回归。support.tar.gz保留初始测试支持源码，supplemental_verify_fixtures.tar.gz补充两组Verify输入；before_source.tar.gz为隔离同步前现场。详细日志和构建文件保留运行目录，归档只收结果摘要及源码，不复制仿真明细。',
    '旧check_ablation.py默认比较历史迁移周期，不用于验收本次有意改变周期与压缩数的后端；其static-only模式仍用于60组ROM核对。报告按60秒刷新，全部结束后刷新进程退出。','',
    '```bash',
    'MHBS_DESIGN=t HASH_BACKEND=sha2 bash scripts/simulate_fast.sh slh_128f sign 1 1',
    'MHBS_DESIGN=c python3 scripts/check_sha2_prefix_cache.py --pipeline 4 --unroll 1','```']
(ARCHIVE/'reports/SHA2_Main_Sync_20261023.md').write_text('\n'.join(lines)+'\n')
for name,dest in [('INITIAL_STATE.json','initial_validation_summary.json'),('RETRY.json','supplemental_validation_summary.json'),
    ('TARGET_BEFORE.json','TARGET_BEFORE.json'),('TARGET_VALIDATION.json','current_c_validation_summary.json'),('TARGET_SOURCE.json','CURRENT_SOURCE.json')]:
    shutil.copy2(RUN/name,ARCHIVE/dest)
shutil.copy2(RUN/'static_rom/VALIDATION_SUMMARY.json',ARCHIVE/'static_rom_summary.json')
shutil.copy2(RUN/'target_before_source.tar.gz',ARCHIVE/'target_before_source.tar.gz')
shutil.copy2(ARCHIVE/'rtl.tar.gz',ARCHIVE/'isolated_rtl.tar.gz')
with tarfile.open(ARCHIVE/'rtl.tar.gz','w:gz') as tar:tar.add(TS/'rtl',arcname='rtl')
for name in ('validate.py','validate_target.py','finalize.py'):shutil.copy2(RUN/name,ARCHIVE/name)
coverage=ARCHIVE/'validation_summary';coverage.mkdir(exist_ok=True)
for d in ('i','c','t'):
    shutil.copy2(SOURCE/f'build/ablation/{d}/recipe_check/P1U1_sha2/coverage.json',coverage/f'recipes_{d}.json')
for p in (SOURCE/'build/ablation/c/sha2_prefix_cache').rglob('coverage.json'):
    shutil.copy2(p,coverage/f'prefix_{p.parent.name}.json')
shutil.copy2(SOURCE/'build/ablation/c/sha256_check/VALIDATION.json',coverage/'sha256_primitive.json')
for root in (ISO,TARGET):
    meta_file=root/'DESIGNS.json';meta=json.loads(meta_file.read_text())
    for d in ('i','c','t'):
        entry=meta['designs'][d];entry['includes_uncommitted_changes']=True
        for f in ('sha2-recipe.sv','sha256.sv'):
            path=f'rtl/{d}/hash/{f}';entry['sha256'][path]=sha(root/path)
        entry['sha2_synchronization']=dict(from_commit=before['upstream_commit'],experiment=str(REL),validation='passed',
            slh128f_sign_cycles=next(x['cycles'] for x in targets if x['design']==d),area_and_atp='not remeasured for synchronized RTL')
    meta_file.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    index=root/'docs/manifests/experiments/INDEX.md';text=index.read_text()
    row=f'| 20261023_182056 | main SHA2行为修正同步i／c／t | [报告]({REL.name}/reports/SHA2_Main_Sync_20261023.md) | 36项隔离整核及当前c补验通过；未综合布线 |'
    old_rows=text.splitlines();old_rows=[row if 'sync_sha2_main_20261023_182056' in line else line for line in old_rows]
    if not any('sync_sha2_main_20261023_182056' in line for line in old_rows):old_rows.append(row)
    index.write_text('\n'.join(old_rows)+'\n')
(ARCHIVE/'ARTIFACTS.json').write_text(json.dumps(dict(complete=True,files={str(p.relative_to(ARCHIVE)):dict(sha256=sha(p),bytes=p.stat().st_size) for p in sorted(ARCHIVE.rglob('*')) if p.is_file() and p.name!='ARTIFACTS.json'}),indent=2)+'\n')
target_archive=TARGET/REL
assert not target_archive.exists()
shutil.copytree(ARCHIVE,target_archive)
for archive in (ARCHIVE,target_archive):
    artifact=json.loads((archive/'ARTIFACTS.json').read_text());assert all(sha(archive/p)==v['sha256'] for p,v in artifact['files'].items())
print(json.dumps(dict(passed=True,current_branch='ablation',targets=targets,report=str(target_archive/'reports/SHA2_Main_Sync_20261023.md')),ensure_ascii=False,indent=2))
