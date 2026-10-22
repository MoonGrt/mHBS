#!/usr/bin/env python3
"""Audit isolated i/c/t copies and replay Verify without changing design files."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = ('shake', 'sha2')
PROFILES = ('slh_128f', 'xmss_h10', 'lms_h10')
BASELINES = {
    'i': 'image_optimization_20261021_182828',
    'c': 'macro_atp_acceptance_20261021_161437',
    't': 'macro_atp_acceptance_20261021_164159',
}


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root)


def audit_copies(designs):
    output = {}
    for key, design in designs.items():
        package = ROOT / key
        missing = []
        changed = []
        for name, expected in design['sha256'].items():
            path = package / name
            if not path.is_file():
                missing.append(name)
            elif sha(path) != expected:
                changed.append(name)
        source = Path(design['source_worktree'])
        source_check = {'available': source.is_dir()}
        if source.is_dir():
            source_check.update(
                head=git(source, 'rev-parse', 'HEAD').decode().strip(),
                status=git(source, 'status', '--porcelain').decode(),
                tracked_diff_sha256=hashlib.sha256(git(source, 'diff', '--binary', 'HEAD')).hexdigest(),
            )
            source_check['unchanged'] = (
                source_check['head'] == design['head'] and
                source_check['status'] == design['source_status'] and
                source_check['tracked_diff_sha256'] == design['tracked_diff_sha256']
            )
        else:
            source_check['unchanged'] = None
        sources = [line.strip() for line in (package / 'sources.txt').read_text().splitlines() if line.strip()]
        unresolved = [name for name in sources if not (package / name).is_file()]
        output[key] = dict(files_checked=len(design['sha256']), missing=missing, changed=changed,
                           unresolved_sources=unresolved, source_worktree=source_check,
                           passed=not missing and not changed and not unresolved and source_check['unchanged'] is not False)
    return output


def freeze(archive, designs):
    frozen = {}
    for key, design in designs.items():
        package = ROOT / key
        names = [str(p.relative_to(package)) for p in sorted((package / 'rtl').rglob('*')) if p.is_file()]
        names += ['sources.txt', 'scripts/clock.xdc']
        identities = {name: sha(package / name) for name in names}
        if any(design['sha256'].get(name) != identity for name, identity in identities.items()):
            raise AssertionError(f'{key}: frozen source differs from imported identity')
        folder = archive / 'frozen' / key
        folder.mkdir(parents=True)
        with tarfile.open(folder / 'rtl.tar.gz', 'w:gz') as bundle:
            for name in names:
                bundle.add(package / name, arcname=name, recursive=False)
        atomic(folder / 'SOURCE.json', dict(package=key, original_head=design['head'],
                                           includes_uncommitted_changes=design['includes_uncommitted_changes'],
                                           sha256=identities))
        frozen[key] = dict(rtl_archive=str((folder / 'rtl.tar.gz').relative_to(ROOT)),
                           sha256=sha(folder / 'rtl.tar.gz'), file_count=len(names))
    return frozen


STATIC_PROGRAM = r'''
import hashlib,json
from pathlib import Path
from model.mHBS import compile_image
profiles={'shake':('slh_128f','slh_192f','slh_256f','slh_128s','slh_192s','slh_256s','xmss_h10','xmss_h16','xmss_h20','lms_h10','lms_h15','lms_h20'),
          'sha2':('slh_128f','slh_128s','xmss_h10','xmss_h16','xmss_h20','lms_h10','lms_h15','lms_h20')}
records=[]
for backend,names in profiles.items():
 for name in names:
  image=compile_image(name,hash_backend=backend)
  image.decode(hash_backend=backend)
  folder=Path('tb/vectors')/('sha2' if backend=='sha2' else '')/name/'verify'
  hashes={}
  for field,words in zip(('program','template','descriptor'),(image.program,image.templates,image.descriptors)):
   actual=''.join(f'{word:016x}\n' for word in words).encode()
   expected=(folder/(field+'.mem')).read_bytes()
   if actual != expected: raise AssertionError((backend,name,field,'generated ROM differs'))
   hashes[field]=hashlib.sha256(actual).hexdigest()
  records.append(dict(backend=backend,profile=name,allocated=[len(image.program),len(image.templates),len(image.descriptors)],sha256=hashes,decode_passed=True))
print(json.dumps(dict(passed=True,images=records,full_tree_generation=False)))
'''


def launch(args):
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/ablation_layout' / stamp
    archive = ROOT / 'docs/manifests/experiments' / ('ablation_layout_' + stamp)
    run.mkdir(parents=True)
    archive.mkdir(parents=True)
    manifest = json.loads((ROOT / 'DESIGNS.json').read_text())
    shutil.copy2(__file__, run / 'check_ablation.py')
    metadata = dict(schema='mhbs.ablation.relocation.v1', created_at=now(), root=str(ROOT), run=str(run),
                    archive=str(archive), jobs=args.jobs, designs_manifest_sha256=sha(ROOT / 'DESIGNS.json'),
                    tool='scripts/check_ablation.py', tool_sha256=sha(__file__),
                    synthesize=False, route=False, high_full_trees=False,
                    cases=18, image_configs=60)
    metadata['frozen'] = freeze(archive, manifest['designs'])
    atomic(run / 'SOURCE.json', metadata)
    atomic(archive / 'SOURCE.json', metadata)
    initial = dict(started_at=now(), complete=False, passed=False, tests={}, images={}, before={}, after={})
    atomic(archive / 'VALIDATION_SUMMARY.json', initial)
    index = ROOT / 'docs/manifests/experiments/INDEX.md'
    if not index.exists():
        index.write_text('# 实验索引\n\n| 时间 | 实验 | 报告 | 范围 |\n|---|---|---|---|\n')
    with index.open('a') as handle:
        handle.write(f'| {stamp} | i/c/t relocation | [报告](ablation_layout_{stamp}/reports/Analysis.md) | 原样迁移、60组静态镜像及18项 Verify；无综合或布线 |\n')
    with (run / 'runner.log').open('w') as log:
        process = subprocess.Popen([sys.executable, str(run / 'check_ablation.py'), '--run', str(run)],
                                   cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    atomic(run / 'LAUNCH.json', dict(pid=process.pid, started_at=now(), log=str(run / 'runner.log')))
    print(json.dumps(dict(pid=process.pid, run=str(run), archive=str(archive))))


def execute(run):
    metadata = json.loads((run / 'SOURCE.json').read_text())
    # The worker is copied under build; use its recorded project root.
    global ROOT
    ROOT = Path(metadata['root'])
    archive = Path(metadata['archive'])
    designs = json.loads((ROOT / 'DESIGNS.json').read_text())['designs']
    state = json.loads((archive / 'VALIDATION_SUMMARY.json').read_text())
    lock = threading.Lock()
    baselines = {key: json.loads((ROOT / key / 'docs/manifests/experiments' / BASELINES[key] / 'VALIDATION_SUMMARY.json').read_text()) for key in designs}

    def save():
        state['updated_at'] = now()
        atomic(archive / 'VALIDATION_SUMMARY.json', state)
        reports = archive / 'reports'
        reports.mkdir(exist_ok=True)
        lines = ['# 三粒度设计目录整合验证', '', f"更新时间：{now()}；完成：{state['complete']}；通过：{state['passed']}。", '',
                 '`i` = image，`c` = image-chain C1，`t` = image-chain-tree C3。原设计文件、镜像、工具和历史证据按目录隔离，生产文件不作修改。', '',
                 '本轮仅验证搬迁：60组静态镜像、18项 K1U1 Verify；逐字节输出检查，并与冻结原版本比较周期、Hash/块数、动态指标和前像/结果指纹。指纹为概率性核对。', '',
                 '未运行完整高树 Keygen/Sign；未新增综合或布线；现有面积与时序结论仍绑定各自历史冻结源码。', '',
                 '| 设计 | 后端 | 配置 | 状态 | 周期 | Hash | 块数 |', '|---|---|---|---|---:|---:|---:|']
        for name, record in sorted(state['tests'].items()):
            design, backend, profile = name.split('/')
            lines.append(f"| {design} | {backend} | {profile} Verify | {record['status']} | {record.get('cycles','')} | {record.get('hashes','')} | {record.get('permutations','')} |")
        lines += ['', '综合与时序证据沿用下列原样归档；本次没有新的 hierarchical.rpt / timing.rpt。', '']
        for key in designs:
            path = ROOT / key / 'docs/manifests/experiments' / BASELINES[key] / 'VALIDATION_SUMMARY.json'
            rel = os.path.relpath(path, reports)
            lines.append(f'- `{key}`：[原验收记录]({rel})；[独立历史实验索引]({os.path.relpath(ROOT/key/"docs/manifests/experiments/INDEX.md", reports)})。')
        if state.get('error'):
            lines += ['', '失败原因：' + state['error']]
        (reports / 'Analysis.md').write_text('\n'.join(lines) + '\n')
        atomic(reports / 'Analysis.json', dict(**state, source=metadata))

    def update(section, key, record):
        with lock:
            state[section][key] = record
            save()

    try:
        state['before'] = audit_copies(designs)
        save()
        if not all(record['passed'] for record in state['before'].values()):
            raise AssertionError('Import/source-working-tree identity audit failed')
        for key in designs:
            log = run / f'{key}_static_images.log'
            started = time.monotonic()
            result = subprocess.run([sys.executable, '-c', STATIC_PROGRAM], cwd=ROOT / key,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            log.write_text(result.stdout)
            if result.returncode:
                raise AssertionError(f'{key}: static image generation failed; {log}')
            record = json.loads(result.stdout.splitlines()[-1])
            record.update(seconds=time.monotonic()-started, log=str(log), log_sha256=sha(log))
            update('images', key, record)

        def group(configuration):
            key, backend = configuration
            for profile in PROFILES:
                case = f'{key}/{backend}/{profile}'
                log = run / 'sim' / key / backend / (profile + '_verify.log')
                log.parent.mkdir(parents=True, exist_ok=True)
                started = time.monotonic()
                command = ['bash', 'scripts/simulate_fast.sh', profile, 'verify', '1', '1']
                env = dict(os.environ, HASH_BACKEND=backend, SIM_FAST_OPT_SLOW='-O1', SIM_HASH_TRACE='1', PYTHONDONTWRITEBYTECODE='1')
                try:
                    with log.open('w') as handle:
                        result = subprocess.run(command, cwd=ROOT / key, env=env, stdout=handle, stderr=subprocess.STDOUT)
                    text = log.read_text()
                    if result.returncode:
                        raise AssertionError(f'Verilator compile or Verify failed: {log}')
                    match = re.search(r'STATEFUL_PASS P1U1 op=2 cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)', text)
                    if not match:
                        raise AssertionError('Missing byte-exact Verify PASS')
                    cycles, total, hashes, blocks = map(int, match.groups())
                    trace = json.loads(re.search(r'HASH_TRACE_METRICS (\{[^\n]+)', text)[1])
                    macro = json.loads(re.search(r'MACRO_METRICS (\{[^\n]+)', text)[1])
                    old = baselines[key]['tests'][f'{backend}/{profile}/verify']
                    vector = ROOT / key / 'tb/vectors' / ('sha2' if backend == 'sha2' else '') / profile / 'verify'
                    vector_sha = {p.name: sha(p) for p in vector.glob('*.mem')}
                    if vector_sha != old['vectors_sha256']:
                        raise AssertionError('Default vector differs from certified original')
                    if (cycles, total, hashes, blocks) != (old['cycles'], old['total_cycles'], old['hashes'], old['permutations']):
                        raise AssertionError('Relocation changed cycles or Hash work')
                    if trace != old['primitive_trace'] or macro != old['macro_metrics']:
                        raise AssertionError('Relocation changed primitive fingerprint or dynamic instruction metrics')
                    record = dict(status='passed', cycles=cycles, total_cycles=total, hashes=hashes, permutations=blocks,
                                  primitive_trace=trace, macro_metrics=macro, exact_baseline_match=True,
                                  vectors_sha256=vector_sha, command=command, env={name: env[name] for name in ('HASH_BACKEND','SIM_FAST_OPT_SLOW','SIM_HASH_TRACE')},
                                  seconds=time.monotonic()-started, log=str(log), log_sha256=sha(log))
                except Exception as error:
                    record = dict(status='failed', error=str(error), log=str(log), seconds=time.monotonic()-started)
                update('tests', case, record)
                print(case, record['status'], flush=True)

        with ThreadPoolExecutor(max_workers=metadata['jobs']) as pool:
            list(pool.map(group, [(key, backend) for key in designs for backend in BACKENDS]))
        state['after'] = audit_copies(designs)
        state['passed'] = (len(state['tests']) == 18 and all(record['status'] == 'passed' for record in state['tests'].values())
                           and all(record['passed'] for record in state['after'].values())
                           and sum(len(record['images']) for record in state['images'].values()) == 60)
    except Exception as error:
        state['error'] = str(error)
        state['passed'] = False
        print('ERROR:', error, flush=True)
    state['complete'] = True
    state['finished_at'] = now()
    save()
    atomic(archive / 'ARTIFACTS.json', dict(schema='mhbs.ablation.artifacts.v1', omitted=['detailed simulation logs'],
           sha256={str(p.relative_to(archive)): sha(p) for p in sorted(archive.rglob('*')) if p.is_file() and p.name != 'ARTIFACTS.json'}))
    print(json.dumps(dict(complete=True, passed=state['passed'], archive=str(archive))), flush=True)
    return 0 if state['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch', action='store_true')
    parser.add_argument('--run', type=Path)
    parser.add_argument('--jobs', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 3:
        parser.error('--jobs must be 1..3')
    if args.run:
        return execute(args.run.resolve())
    launch(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
