#!/usr/bin/env python3
"""Audit source-list diagnostics, macro placement and optional signature storage.

This verifies preprocessed source, rather than relying on zero-valued outputs.
Run audit_debug.tcl after Vivado synthesis to audit actual ports and registers.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC = re.compile(
    r"\b(?:[A-Za-z0-9_]*error_code|(?:[A-Za-z0-9_]+_)?(?:cycles|hash_count|"
    r"permutation_count|hash_base|permutation_base)|batch_hashes|batch_permutations|"
    r"diagnostic_[A-Za-z0-9_]+|(?:lane|pipe|total)_(?:hashes|permutations))\b"
)
COMMENT_STRING = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"')
TOKEN = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*\b|[()@;]')


def code_only(text):
    # Preserve offsets so directive positions can be compared with always bodies.
    return COMMENT_STRING.sub(lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), text)


def procedural_macro_lines(text):
    clean = code_only(text)
    tokens = list(TOKEN.finditer(re.sub(r'`[^\n]*', lambda m: ' ' * len(m[0]), clean)))
    result = []
    for i, token in enumerate(tokens):
        if token[0] not in ('always', 'always_ff', 'always_comb', 'always_latch'):
            continue
        cursor = i + 1
        if cursor < len(tokens) and tokens[cursor][0] == '@':
            cursor += 1
            if tokens[cursor][0] == '(':
                depth = 1
                cursor += 1
                while depth and cursor < len(tokens):
                    depth += (tokens[cursor][0] == '(') - (tokens[cursor][0] == ')')
                    cursor += 1
        # Production functional blocks all use begin/end. For compact always
        # statements, inspect through their first terminating semicolon.
        depth = 0
        end = token.end()
        for body in tokens[cursor:]:
            depth += (body[0] == 'begin') - (body[0] == 'end')
            end = body.end()
            if body[0] == 'end' and depth == 0:
                break
            if body[0] == ';' and depth == 0:
                break
        for guard in re.finditer(r'`(?:ifn?def|elsif)\s+SYNTHESIS\b', clean[token.end():end]):
            result.append(text.count('\n', 0, token.end() + guard.start()) + 1)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hash',dest='hash_backend',choices=('shake','sha2'),default='shake')
    parser.add_argument('--output', default='build/debug_cleanup/source_audit.json')
    parser.add_argument('--lint', action='store_true', help='Lint all four top macro views')
    args = parser.parse_args()
    sources = [line.strip() for line in (ROOT / 'sources.txt').read_text().splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
    failures = []
    placements = {}
    for source in sources:
        text = (ROOT / source).read_text()
        placements[source] = procedural_macro_lines(text)
        if placements[source]:
            failures.append(f'{source}: SYNTHESIS guard inside always at {placements[source]}')
        if re.search(r'\bPROFILE_ENABLE\b|\bSIGNATURE_STORE_ENABLE\b', code_only(text)):
            failures.append(f'{source}: removed parameter remains')
    verilator = os.environ.get('VERILATOR', 'verilator')
    views = []
    output = ROOT / args.output
    if args.hash_backend=='sha2' and args.output=='build/debug_cleanup/source_audit.json': output=ROOT/'build/debug_cleanup_sha2/source_audit.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    for synthesis in (False, True):
        for signature in (False, True):
            name = f'synthesis{int(synthesis)}_signature{int(signature)}'
            defines = (['-DSYNTHESIS'] if synthesis else []) + (['-DMHBS_SIGNATURE_STORE'] if signature else [])
            if args.hash_backend=='sha2':defines.append('-DMHBS_SHA2')
            command = [verilator, '-E', '--language', '1800-2017', *defines, *sources]
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            if result.returncode:
                failures.append(f'{name}: preprocessing failed: {result.stderr[-2000:]}')
                continue
            clean = code_only(result.stdout)
            diagnostic_names = sorted(set(DIAGNOSTIC.findall(clean)))
            if synthesis and diagnostic_names:
                failures.append(f'{name}: diagnostic identifiers remain: {diagnostic_names}')
            top = re.search(r'\bmodule\s+top\b[\s\S]*?\bendmodule\b', clean)
            declared = bool(top and re.search(r'\bsignature\s+\w+\s*\(', top[0]))
            enable = re.search(r'\bSIGNATURE_STORE_PRESENT\s*=\s*([01])', top[0] if top else '')
            instance = declared and (not enable or enable[1] == '1')
            if instance != signature:
                failures.append(f'{name}: signature instance={instance}, expected={signature}')
            log = output.parent / f'{name}.preprocessed.sv'
            log.write_text(result.stdout)
            lint_passed = None
            if args.lint:
                lint_command = [verilator, '--lint-only', '-Wno-fatal', '--top-module', 'top',
                                '-GPIPELINE=4', '-GUNROLL=1', *defines, *sources]
                lint = subprocess.run(lint_command, cwd=ROOT, text=True, capture_output=True)
                (output.parent / f'{name}.lint.log').write_text(lint.stdout + lint.stderr)
                lint_passed = lint.returncode == 0
                if not lint_passed:
                    failures.append(f'{name}: lint failed; see {name}.lint.log')
            views.append(dict(name=name, diagnostics_present=diagnostic_names,
                              signature_instance=instance, lint_passed=lint_passed,
                              preprocessed_sha256=hashlib.sha256(result.stdout.encode()).hexdigest()))
    report = dict(hash_backend=args.hash_backend,passed=not failures, scope='sources.txt and four preprocessed top views',
                  source_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources},
                  procedural_macro_lines=placements, views=views, failures=failures)
    output.write_text(json.dumps(report, indent=2) + '\n')
    for failure in failures:
        print(failure)
    print(f'RTL_DEBUG_AUDIT_{"PASS" if not failures else "FAIL"} {output}')
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
