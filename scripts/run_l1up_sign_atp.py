#!/usr/bin/env python3
"""Single-lane U1 P1-P4 128f sign sweep, synthesis only at assumed 150 MHz."""
import argparse
import csv
import json
import re
import shutil
import subprocess
import tarfile
from v42_external_flow import ROOT, BASE, simulate_case, build_binary, run, write, sha
from run_lup_sign_atp import snapshot, synth, check_same, FREQ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='l1up_128f_20261007_v1')
    args = ap.parse_args()
    assert re.fullmatch('[a-zA-Z0-9_-]+', args.tag)
    out = ROOT/'manifests/experiments'/args.tag
    build = ROOT/'build'/args.tag
    out.mkdir(parents=True, exist_ok=True)
    build.mkdir(parents=True, exist_ok=True)
    identity = snapshot(out)
    (out/'implementation.patch').write_bytes(subprocess.check_output(['git', 'diff', 'HEAD'], cwd=ROOT))
    reference_path = ROOT/'manifests/experiments/lup_shared_128f_20261007_v2/simulation.json'
    reference = json.loads(reference_path.read_text())
    write(out/'configuration.json', dict(lanes=1, unroll=1, pipelines=[1,2,3,4], profile='slh_128f', operation='sign', assumed_mhz=FREQ, routed=False, reference=str(reference_path.relative_to(ROOT)), reference_sha256=sha(reference_path)))
    vector = BASE/'vectors/slh_128f/sign'
    points, checks = {}, {}

    def sim(name, p, **kwargs):
        return simulate_case(build, name, vector, unroll=1, pipeline=p, lanes=kwargs.pop('lanes',1), **kwargs)[1]

    for p in (1,2,3,4):
        result = sim(f'L1U1P{p}',p)
        check_same(result,reference['points'][str(p)],cycles=False)
        points[p] = result
        off = sim(f'L1U1P{p}_stats_off',p,profile_enable=False)
        check_same(off,result)
        checks[f'P{p}_stats_off'] = off
        replay = sim(f'L1U1P{p}_replay_stall',p,options=('+REPLAYS=2','+STALL=1','+INTERRUPT=1','+TAIL_NOISE=1'))
        assert (replay['hashes'],replay['permutations']) == (result['hashes'],result['permutations'])
        checks[f'P{p}_replay_stall'] = replay
    for p in (1,4):
        result = sim(f'L2U1P{p}_regression',p,lanes=2)
        check_same(result,reference['points'][str(p)])
        checks[f'L2P{p}_unchanged'] = result
    checks['partition'] = sim('L1U1P4_partition',4,partitioned=True)
    check_same(checks['partition'],points[4])
    checks['swap'] = sim('L1U1P3_swap',3,swap=1)
    check_same(checks['swap'],points[3])
    binary = build_binary(build,json.loads((vector/'job.json').read_text()),unroll=1,pipeline=4,lanes=1)
    for mode in (1,2):
        log=build/'logs'/f'L1U1P4_fault_{mode}.log'
        run([str(binary),f'+IMAGE={BASE/"images/slh_128f"}',f'+VECTOR={vector}',f'+FAULT={mode}'],log)
        assert 'V42_FAULT_PASS' in log.read_text()
        checks[f'fault_{mode}'] = dict(passed=True,log_sha256=sha(log))
    write(out/'simulation.json',dict(points=points,checks=checks))
    shutil.copytree(build/'logs',out/'simulation',dirs_exist_ok=True)
    ws=build/'synth_source'
    ws.mkdir(exist_ok=True)
    with tarfile.open(out/'source_snapshot.tar.gz') as t:
        t.extractall(ws,filter='data')
    for path,h in identity.items():
        assert sha(ws/path)==h,path
    rows=[]
    for p in (1,2,3,4):
        a=synth(out,p,ws,lanes=1)
        # The second lane must not exist in the synthesized hierarchy.
        hierarchy=(out/f'L1U1P{p}'/'core_hierarchical.rpt').read_text()
        assert 'lanes[1]' not in hierarchy
        write(out/f'L1U1P{p}'/'lane_audit.json',dict(passed=True,lanes=1,second_lane_present=False))
        s=points[p]
        ms=s['sign_cycles']/(FREQ*1000)
        row=dict(point=f'L1U1P{p}',**a,compute_cycles=s['sign_cycles'],total_cycles=s['total_cycles'],hashes=s['hashes'],permutations=s['permutations'],assumed_mhz=FREQ,time_ms=ms,atp_slice_ms=a['equivalent_slice']*ms,keccak_round_utilization=s['permutations']*24/(p*s['sign_cycles']))
        rows.append(row)
        write(out/f'L1U1P{p}'/'result.json',row)
    for r in rows:
        r['speedup']=rows[0]['compute_cycles']/r['compute_cycles']
        r['relative_atp']=r['atp_slice_ms']/rows[0]['atp_slice_ms']
    write(out/'results.json',dict(scope='128f sign common core',frequency_basis='assumed 150 MHz; no place/route',points=rows))
    with (out/'results.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
    report='# L1U1P1–P4：128f sign 共同核 ATP\n\n'
    report+='150 MHz 为假定频率，未经布局布线验证。历史 K 与当前 L 同义。共同核面积包含上下文、流水和结果暂存，不含顶层签名存储；LUT 已包含 LUTRAM。单 lane 仅实例化一个 recipe lane，窗口为 P 个独立上下文，端点按地址奇偶写入原双银行存储。默认 L2U2P1 不变。\n\n'
    report+='| 配置 | LUT | FF | LUTRAM | BRAM36 | 等效 Slice | 计算周期 | 总周期 | 时间 ms | ATP Slice·ms | 相对 P1 ATP | Keccak 利用率 |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n'
    for r in rows:
        report+=f"| {r['point']} | {r['lut']:.0f} | {r['ff']:.0f} | {r['lutram']:.0f} | {r['bram36']:g} | {r['equivalent_slice']:.3f} | {r['compute_cycles']} | {r['total_cycles']} | {r['time_ms']:.6f} | {r['atp_slice_ms']:.3f} | {r['relative_atp']:.4f} | {r['keccak_round_utilization']:.2%} |\n"
    report+='\n等效 Slice = LUT/4 + FF/8 + BRAM36×232.4 + DSP×102.4。时间 = 计算周期/150000 ms；ATP = 等效 Slice×时间。Keccak 利用率 = 置换次数×24 / (L×U×P×计算周期)，表示有效轮运算占物理轮容量的比例。\n\n'
    report+='四组签名逐字节通过软件参考比较，Hash/置换次数均为 104937/105641；统计关闭输出和周期一致。四组输入停顿、复位中断与连续重放，P3 单 lane 交换，P4 共同核等价和两项异常退出均通过。现有存储、父节点操作数及输出来源监视器同时运行。L2U1P1/P4 的输出、周期与此前冻结测量一致。单 lane 新配置本轮只验证 128f sign，其他参数集与操作尚未验证。\n\n'
    report+=f'源码快照、配置、日志、CSV/JSON 及分层面积报告：`manifests/experiments/{args.tag}/`。各点 `core_hierarchical.rpt` 为分层报告；综合关闭统计并检查计数寄存器裁剪。没有测量新频率。\n'
    (out/'report.md').write_text(report)
    (ROOT/'docs/v4.2/L1UP_128f_Sign_ATP.md').write_text(report)
    write(out/'evidence_sha256.json',{str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='evidence_sha256.json' and p.suffix!='.dcp'})
    print('L1UP_SWEEP_PASS',out/'report.md',flush=True)

if __name__=='__main__':
    main()
