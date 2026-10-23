#!/usr/bin/env python3
"""Measure timing/routing RTL repairs, then start the authorized full matrix."""
import argparse
from pathlib import Path

import run_timing_n as workflow

ROOT = workflow.ROOT
workflow.FAMILY, workflow.REPORT_STEM = 'timing_o', 'Timing_O'
workflow.ENTRYPOINT = 'run_timing_o.py'
workflow.LABEL = 'O1_generic_Keccak_word_locality_SHA2_predecode_congestion_spread'
workflow.TITLE = 'O：时序、布线拥塞优化与全矩阵交接'
workflow.DESCRIPTION = (
    'SHAKE使用通用64位Theta/Chi局部组合层级，保留原RAM和寄存边沿；'
    'SHA2将有效标量发布收于tag0，提前登记列表字选择和地址，保留SHA256压缩层级。'
    '全部P/U统一使用AltSpreadLogic_high布局、默认物理优化、Explore路由。'
    '周期设计不变，最终以逐项Sign实测为准。')
workflow.POINTS = (
    ('shake', 3, 2), ('shake', 12, 1), ('shake', 24, 1),
    ('sha2', 6, 1), ('sha2', 8, 1), ('sha2', 12, 1), ('sha2', 24, 1))
workflow.BASE = ROOT / 'build/dual_pu_route_matrix/20261022_220001'
workflow.BASE_SHA = '23bdc80bd6098b0f73e80e4a9b62ce5521c7b40eef6b0c990afaec2346fc711d'
# New baseline and changed RTL: avoid all previous N diagnostic reuse.
workflow.DIAGNOSTIC_CACHE = ROOT / 'build/timing_o/no_diagnostic_cache'
# A resource planning filter, not a user acceptance threshold. The complete
# matrix still reports every point's actual area, frequency, cycles and ATP.
workflow.AREA_GROWTH_LIMIT = .05
workflow.CONTROLS = tuple(dict.fromkeys(('run_timing_o.py', *workflow.CONTROLS)))
workflow.MICRO_SOURCES = (
    ('build/timing_o_micro_keccak/SUMMARY.json', 'rtl/hash/keccak.sv', 'source_sha256'),
    ('build/timing_o_micro_sha2/SUMMARY.json', 'rtl/hash/sha2-recipe.sv', 'source_sha256'))


def prepare_micro_summaries():
    shake = workflow.read(ROOT / 'build/o_shake_word_locality/SUMMARY.json')
    assert shake['passed'] and shake['generic_mapping']
    assert all(workflow.sha(ROOT / n) == h for n, h in shake['rtl_sha256'].items())
    tests = []
    for test in shake['logs']:
        assert test['passed'] and workflow.sha(ROOT / test['log']) == test['sha256']
        tests.append(dict(test, log_sha256=test['sha256']))
    workflow.write(ROOT / workflow.MICRO_SOURCES[0][0], dict(
        source_sha256=shake['rtl_sha256']['rtl/hash/keccak.sv'], tests=tests, original_summary=shake))
    sha2 = workflow.read(ROOT / 'build/timing_o_sha2_micro/SUMMARY.json')
    assert not sha2['pending']
    assert workflow.sha(ROOT / 'rtl/hash/sha2-recipe.sv') == sha2['sha2_recipe_sha256']
    assert all(t['identical'] for t in sha2['full_sign_baseline_comparison'])
    tests = []
    for test in sha2['tests']:
        log = ROOT / test['log']
        assert test['pass_markers']
        text = log.read_text(errors='replace')
        assert all(marker in text for marker in test['pass_markers'])
        tests.append(dict(test, passed=True, log_sha256=workflow.sha(log)))
    workflow.write(ROOT / workflow.MICRO_SOURCES[1][0], dict(
        source_sha256=sha2['sha2_recipe_sha256'], tests=tests, original_summary=sha2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--launch', action='store_true')
    mode.add_argument('--run-root', type=Path)
    args = parser.parse_args()
    if args.launch:
        prepare_micro_summaries()
        workflow.launch()
    else:
        raise SystemExit(workflow.Runner(args.run_root.resolve()).execute())
