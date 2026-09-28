"""Check that the candidate changes only the elaboration of two recipe lanes.

Run from the candidate checkout, or pass its source root as the first argument.
The repository must contain baseline commit b4816c0.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
commit = 'b4816c0c411f298bfd49f2f1f0885279683618bc'

def old(path):
    return subprocess.check_output(['git', 'show', f'{commit}:{path}'], cwd=root)

path = 'rtl/top/mhbs_hbs.sv'
baseline = old(path).decode()
candidate = (root / path).read_text()
start = baseline.index('    genvar physical;')
end = baseline.index('    initial if(LANES', start)
body = baseline[baseline.index('        mhbs_recipe_lane', start):baseline.index('    end\n    endgenerate', start)]
instances = []
for lane in range(2):
    instance = re.sub(r'\bL\b', f'L{lane}', body).replace(')) lane (', f')) lane{lane} (')
    instances.append(f'    localparam integer L{lane}=SWAP_PHYSICAL_LANES ? {1-lane} : {lane};\n' + instance)
assert candidate == baseline[:start] + ''.join(instances) + baseline[end:]
unchanged = {}
for path in (root / 'manifests/v42_sources.txt').read_text().split():
    if path == 'rtl/top/mhbs_hbs.sv':
        continue
    source = (root / path).read_bytes()
    assert source == old(path), path
    unchanged[path] = hashlib.sha256(source).hexdigest()
print(json.dumps(dict(passed=True, baseline_commit=commit,
                     changed_rtl=['rtl/top/mhbs_hbs.sv'],
                     lane_instance_expansion_exact=True,
                     other_rtl_byte_identical=True,
                     unchanged_rtl_sha256=unchanged), indent=2))
