#!/usr/bin/env python3
"""Validate the frozen SHAKE timing candidate without production edits."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'sources.txt').is_file() and (p/'rtl').is_dir())
OUT = ROOT / 'build/c2_timing_optimization/validation_r4'
RUN = ROOT / 'build/c2_timing_optimization/candidate_20261020_100009'
SOURCE = RUN / 'source'
MANIFEST = RUN / 'SOURCE.json'
META = json.loads(MANIFEST.read_text())
EXPECTED = META['sha256']
LOCK = threading.Lock()
RESULTS = []
START = time.time()
TOTAL = 59
SCOPE = 'R4 frozen source: P4/P12 published+deferred pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. P1U1 all scalar recipes and three-profile Verify smoke; P6U1 three-target full Sign exercises 8-leaf FORS microgroups in 6+2 waves and odd L-tree. Root executes P4/P12 six SHAKE Sign independently. No h20 Keygen/Sign.'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def mismatches():
    return [name for name, digest in EXPECTED.items()
            if not (SOURCE/name).is_file() or sha(SOURCE/name) != digest]

def publish(complete=False):
    with LOCK:
        failures = [x for x in RESULTS if not x['passed']]
        changed = mismatches()
        data = dict(schema='mhbs.shake_timing.functional_validation.v1',
                    candidate_run=str(RUN), source_root=str(SOURCE),
                    source_manifest=str(MANIFEST), source_manifest_sha256=sha(MANIFEST),
                    rtl_sha256={k:v for k,v in EXPECTED.items() if k.startswith('rtl/')},
                    recipe_sha256=EXPECTED['rtl/hash/shake-recipe.sv'],
                    hash_backend='shake_and_sha2', complete=complete,
                    status='failed' if failures or changed else 'passed' if complete else 'running',
                    passed=len(RESULTS)-len(failures), failed=len(failures),
                    total_planned=TOTAL, source_unchanged=not changed,
                    source_mismatches=changed, elapsed_seconds=time.time()-START,
                    scope=SCOPE,
                    tests=list(RESULTS))
        tmp = OUT/'VALIDATION.json.tmp'
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
        tmp.replace(OUT/'VALIDATION.json')

def run_case(name, command, kind, **meta):
    started = time.time()
    log = OUT/'logs'/f'{name}.log'
    env = os.environ.copy()
    env.update(HASH_BACKEND=meta.get('backend','shake'), SIM_SYNTHESIS='0', KECCAK_LUT6='0', SIM_FAST_OPT_SLOW='-O1')
    env.pop('PROFILE_ENABLE', None)
    with log.open('w') as stream:
        try:
            process = subprocess.run(command, cwd=SOURCE, env=env,
                                     stdout=stream, stderr=subprocess.STDOUT,
                                     timeout=1800)
            code = process.returncode
            error = None
        except Exception as exc:
            code = -1
            error = repr(exc)
    result = dict(name=name, kind=kind, command=command, passed=code==0,
                  returncode=code, elapsed_seconds=time.time()-started,
                  log=str(log), log_sha256=sha(log), **meta)
    if error: result['error']=error
    if code==0:
        result['pass_markers']=[line for line in log.read_text(errors='replace').splitlines()
                                if any(marker in line for marker in
                                       ('STATEFUL_PASS', 'STATEFUL_FAULT_PASS', 'RECIPE_PASS', 'RECIPE_CHECK_PASS', 'PIPELINE_PASS', 'INDEX_REJECT_PASS'))]
    with LOCK:
        RESULTS.append(result)
    publish()
    print(f"{'PASS' if code==0 else 'FAIL'} {name} {result['elapsed_seconds']:.1f}s", flush=True)
    if code:
        print(log.read_text(errors='replace')[-8000:], flush=True)
    return code==0

def core_group(p):
    for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
        common = ['bash', 'scripts/simulate.sh', profile, 'verify', str(p), '1']
        run_case(f'verify_P{p}U1_{profile}_stall_replay_reset_cut',
                 common+['+STALL=1', '+REPLAYS=2', '+INTERRUPT=1', '+CUT=1'],
                 'verify', p=p, u=1, profile=profile, coverage=['stall','replays','inflight_reset','truncation_recovery'])
        for tamper in range(1,6):
            run_case(f'verify_P{p}U1_{profile}_tamper{tamper}',
                     common+['+STALL=1',f'+TAMPER={tamper}'],
                     'tamper', p=p,u=1, profile=profile, tamper=tamper)
    for fault in (1,2,3):
        run_case(f'fault_P{p}U1_xmss_h10_{fault}',
                 ['bash','scripts/simulate.sh','xmss_h10','verify',str(p),'1',f'+FAULT={fault}'],
                 'fault',p=p,u=1, profile='xmss_h10',fault=fault)

def recipe_group():
    for p,u,synthesis in ((4,1,True),(12,1,True),(2,12,False),(2,12,True)):
        run_case(f'recipes_P{p}U{u}_synthesis{int(synthesis)}',
                 ['python3','scripts/check_recipes.py','--hash','shake',
                  '--pipeline',str(p),'--unroll',str(u)]+(['--synthesis'] if synthesis else []),
                 'recipes',p=p,u=u,synthesis=synthesis)

def pipeline_group():
    for p,synthesis in ((4,False),(12,False),(4,True),(12,True)):
        run_case(f'pipeline_P{p}U1_synthesis{int(synthesis)}',
                 ['python3','scripts/check_pipeline.py','--hash','shake',
                  '--pipeline',str(p),'--unroll','1']+(['--synthesis'] if synthesis else []),
                 'pipeline',p=p,u=1,synthesis=synthesis,
                 coverage=['published_response_KAT','deferred_response_KAT','held_payload','same_edge_retire_refill','zero_step','poison_invalid_request','out_of_order','address_boundaries'])

def extra_group():
    run_case('verify_P2U12_xmss_h10_stall_replay_reset_cut',
             ['bash','scripts/simulate.sh','xmss_h10','verify','2','12',
              '+STALL=1','+REPLAYS=2','+INTERRUPT=1','+CUT=1'],
             'verify',p=2,u=12,profile='xmss_h10')
    run_case('sha2_sign_P4U1_slh_128f',
             ['bash','scripts/simulate_fast.sh','slh_128f','sign','4','1'],
             'sign_compatibility',p=4,u=1,profile='slh_128f',backend='sha2')

def scalar_smoke_group():
    run_case('recipes_P1U1_synthesis0',
             ['python3','scripts/check_recipes.py','--hash','shake','--pipeline','1','--unroll','1'],
             'recipes',p=1,u=1,synthesis=False)
    for profile in ('slh_128f','xmss_h10','lms_h10'):
        run_case(f'verify_P1U1_{profile}_smoke',
                 ['bash','scripts/simulate.sh',profile,'verify','1','1','+STALL=1'],
                 'verify_smoke',p=1,u=1,profile=profile)

def p6_sign_group():
    for profile in ('slh_128f','xmss_h10','lms_h10'):
        run_case(f'sign_P6U1_{profile}',
                 ['bash','scripts/simulate_fast.sh',profile,'sign','6','1'],
                 'sign_p6',p=6,u=1,profile=profile,
                 coverage=['full_signature_KAT','signature_cache','hash_permutation_counts','non_four_multiple_batch','FORS_6_plus_2_waves' if profile=='slh_128f' else 'odd_Ltree' if profile=='xmss_h10' else 'long_list'])

def finalize_summary():
    import shutil
    data=json.loads((OUT/'VALIDATION.json').read_text())
    data['h20_full_keygen_sign_run']=False
    data['pipeline_live_tag_scope']='Four live tags per P4/P12 KAT; full P12 occupancy is covered separately by full Sign.'
    data['aggregate_cases']=dict(command_groups=59,pipeline_kat_command_groups=4,
        pipeline_family_address_groups=48,pipeline_requests=384,scalar_recipe_kat_cases=2295,
        verify_stall_reset_replay_cut_groups=7,verify_p1_smoke_groups=3,tamper_groups=30,
        injected_fault_groups=6,sha2_full_sign_groups=1,p6_full_sign_groups=3)
    (OUT/'VALIDATION.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    sign_rows=[]
    for test in data['tests']:
        if test['kind'] in ('sign_p6','sign_compatibility'):
            sign_rows.extend(test.get('pass_markers',[]))
    rows='\n'.join('- `'+row+'`' for row in sign_rows)
    md=f"""# R4 功能验证摘要

冻结源码：`{SOURCE}`。源码清单 SHA256：`{data['source_manifest_sha256']}`。

结果：**{data['passed']}/{data['total_planned']} 组通过**，{data['failed']} 失败，耗时 {data['elapsed_seconds']:.3f} 秒；冻结文件 SHA 全部一致：{data['source_unchanged']}。

- 保留原 52 组完整边界套件：P4/P12 发布与延迟读口 KAT、停顿、乱序、同拍补发、零步与请求字段扰动；三算法 Verify 重放/复位/截断、30 组篡改、6 组在途故障；P2U12 配方及 Verify；SHA2 P4 SLH128f 完整 Sign。
- 添加 P1U1 459 条 scalar recipe KAT 和三个目标 Verify 停顿冒烟。
- 添加 P6U1 三个目标完整 Sign；SLH FORS 微组 8 叶、按 6+2 两波，覆盖非四整批；XMSS 包含奇数 L-tree，LMS 包含长列表。
- 全部配方 KAT 共 2,295 条，batch KAT 384 个请求。P12 batch bench 使用 4 个活动 tag，完整 Sign 由主运行器另行覆盖。
- 未执行 h20 完整 Keygen/Sign；未启动 Vivado；未修改生产或冻结 RTL。

完整 Sign 通过行：

{rows}

逐组命令和日志校验见 `VALIDATION.json`；详细原始日志仅留 build 运行目录。
"""
    (OUT/'SUMMARY.md').write_text(md)
    binding=dict(candidate_run=str(RUN),source_manifest=str(MANIFEST),source_manifest_sha256=sha(MANIFEST),
                 rtl_sha256=data['rtl_sha256'],source_unchanged=data['source_unchanged'],
                 reproduction_script_sha256=sha(Path(__file__)))
    (OUT/'SOURCE_BINDING.json').write_text(json.dumps(binding,indent=2)+'\n')
    archive_dir=ROOT/'docs/manifests/experiments/c2_timing_optimization_20261020_100009/validation_summary'
    archive_dir.mkdir(parents=True,exist_ok=True)
    for name in ('VALIDATION.json','SUMMARY.md','SOURCE_BINDING.json'):
        shutil.copy2(OUT/name,archive_dir/name)
    shutil.copy2(Path(__file__),archive_dir/'run_validation.py')
    archive_hashes={name:sha(archive_dir/name)for name in ('VALIDATION.json','SUMMARY.md','SOURCE_BINDING.json','run_validation.py')}
    (archive_dir/'SHA256.json').write_text(json.dumps(archive_hashes,indent=2)+'\n')

if __name__=='__main__':
    (OUT/'logs').mkdir(parents=True,exist_ok=True)
    assert not mismatches(), 'Frozen candidate source mismatch before tests'
    publish()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures=[executor.submit(core_group,4),executor.submit(core_group,12),
                 executor.submit(recipe_group),executor.submit(pipeline_group),
                 executor.submit(scalar_smoke_group),executor.submit(p6_sign_group)]
        for future in concurrent.futures.as_completed(futures): future.result()
    extra_group()
    assert len(RESULTS)==TOTAL,(len(RESULTS),TOTAL)
    publish(complete=True)
    finalize_summary()
    print(json.dumps({k:v for k,v in json.loads((OUT/'VALIDATION.json').read_text()).items()
                      if k in ('status','passed','failed','elapsed_seconds','source_unchanged')},indent=2),flush=True)
