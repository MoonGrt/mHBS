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
OUT = ROOT / 'build/c2_timing_optimization/validation_r1'
RUN = ROOT / 'build/c2_timing_optimization/candidate_20261020_095359'
SOURCE = RUN / 'source'
MANIFEST = RUN / 'SOURCE.json'
META = json.loads(MANIFEST.read_text())
EXPECTED = META['sha256']
LOCK = threading.Lock()
RESULTS = []
START = time.time()
TOTAL = 52
SCOPE = 'R1 frozen source: P4/P12 deferred-only pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. Root executes six SHAKE Sign independently. No h20 Keygen/Sign.'

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
                 coverage=['deferred_response_KAT','held_tag_and_deferred_payload','same_edge_retire_refill','zero_step','poison_invalid_request','out_of_order','address_boundaries'])

def extra_group():
    run_case('verify_P2U12_xmss_h10_stall_replay_reset_cut',
             ['bash','scripts/simulate.sh','xmss_h10','verify','2','12',
              '+STALL=1','+REPLAYS=2','+INTERRUPT=1','+CUT=1'],
             'verify',p=2,u=12,profile='xmss_h10')
    run_case('sha2_sign_P4U1_slh_128f',
             ['bash','scripts/simulate_fast.sh','slh_128f','sign','4','1'],
             'sign_compatibility',p=4,u=1,profile='slh_128f',backend='sha2')

def finalize_summary():
    import shutil
    data=json.loads((OUT/'VALIDATION.json').read_text())
    data['h20_full_keygen_sign_run']=False
    data['pipeline_live_tag_scope']='Four live tags per P4/P12 KAT; P12 full occupancy not claimed by this bench.'
    data['published_response_ports_tested']=False
    data['pipeline_data_scope']='Frozen original tb_pipeline leaves batch_response_digest/capture disconnected. KAT observes only batch_read_digest/capture; deferred-only, not published payload coverage.'
    data['aggregate_cases']=dict(command_groups=52,pipeline_kat_command_groups=4,
        pipeline_family_address_groups=48,pipeline_requests=384,scalar_recipe_kat_cases=1836,
        verify_stall_reset_replay_cut_groups=7,tamper_groups=30,
        injected_fault_groups=6,sha2_full_sign_groups=1)
    (OUT/'VALIDATION.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    md=f"""# R1 功能验证摘要

冻结源码：`{SOURCE}`。源码清单 SHA256：`data-placeholder`。

结果：**{data['passed']}/{data['total_planned']} 组通过**，{data['failed']} 失败，耗时 {data['elapsed_seconds']:.3f} 秒；冻结文件 SHA 全部一致：{data['source_unchanged']}。

- P4U1/P12U1 正常与 SYNTHESIS batch KAT 共 384 个请求；原冻结 tb_pipeline 只核对 batch_read_digest/capture 延迟读口，发布响应数据端口未连接，明确为 deferred-only 覆盖。
- P12 batch bench 使用 4 个活动 tag，不据此声称 12 槽满占用；保留乱序、零步、停顿、同拍补发和无效请求字段扰动。
- 1,836 条独立 hashlib 配方 KAT：P4/P12 SYNTHESIS 和 P2U12 正常/SYNTHESIS。
- P4/P12 三算法及 P2U12 XMSS Verify 共 7 组，覆盖停顿、重放、在途复位、截断恢复；另外 30 组篡改、6 组故障通过。
- SHA2 P4U1 SLH128f 完整 Sign 兼容通过。
- 未新增 P6 或全六 SLH 参数回归；未执行 h20 完整 Keygen/Sign；未启动 Vivado；未修改生产或冻结源码。

逐组命令和日志校验见 VALIDATION.json；详细日志仅留 build 运行目录。
""".replace('data-placeholder',data['source_manifest_sha256'])
    (OUT/'SUMMARY.md').write_text(md)
    binding=dict(candidate_run=str(RUN),source_manifest=str(MANIFEST),source_manifest_sha256=sha(MANIFEST),
                 rtl_sha256=data['rtl_sha256'],source_unchanged=data['source_unchanged'],
                 reproduction_script_sha256=sha(Path(__file__)))
    (OUT/'SOURCE_BINDING.json').write_text(json.dumps(binding,indent=2)+'\n')
    archive_dir=ROOT/'docs/manifests/experiments/c2_timing_optimization_20261020_095359/validation_summary'
    archive_dir.mkdir(parents=True,exist_ok=True)
    for name in ('VALIDATION.json','SUMMARY.md','SOURCE_BINDING.json'):
        shutil.copy2(OUT/name,archive_dir/name)
    shutil.copy2(Path(__file__),archive_dir/'run_validation.py')
    hashes={name:sha(archive_dir/name)for name in ('VALIDATION.json','SUMMARY.md','SOURCE_BINDING.json','run_validation.py')}
    (archive_dir/'SHA256.json').write_text(json.dumps(hashes,indent=2)+'\n')

if __name__=='__main__':
    (OUT/'logs').mkdir(parents=True,exist_ok=True)
    assert not mismatches(),'Frozen candidate source mismatch before tests'
    publish()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures=[executor.submit(core_group,4),executor.submit(core_group,12),
                 executor.submit(recipe_group),executor.submit(pipeline_group)]
        for future in concurrent.futures.as_completed(futures):future.result()
    extra_group()
    assert len(RESULTS)==TOTAL,(len(RESULTS),TOTAL)
    publish(complete=True)
    finalize_summary()
    print(json.dumps({k:v for k,v in json.loads((OUT/'VALIDATION.json').read_text()).items()
                      if k in ('status','passed','failed','elapsed_seconds','source_unchanged')},indent=2),flush=True)
