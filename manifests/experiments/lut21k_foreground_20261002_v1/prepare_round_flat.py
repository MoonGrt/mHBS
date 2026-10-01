import json,tarfile,shutil,difflib,hashlib
from pathlib import Path
root=Path.cwd();r=root/'manifests/experiments/lut21k_foreground_20261002_v1';base=Path('manifests/experiments/unified_hbs_v4.2/external_job_message');tag='lut21k_20261002_v1_round_flat';w=root/'build/v4.2/lut21k_workspaces'/tag;w.mkdir(exist_ok=False)
with tarfile.open(root/base/'candidates/lut21k_20261002_v1_bank/source_snapshot.tar.gz') as t:t.extractall(w,filter='data')
p=w/base/'candidates/parent_right_20260930_v1';p.mkdir(parents=True);shutil.copy2(root/base/'candidates/parent_right_20260930_v1/simulation.json',p/'simulation.json')
rel='rtl/hash_lane/mhbs_compact_shake_context_lane.sv';p=w/rel;s=p.read_text();assert s.count('(* keep_hierarchy="yes" *) mhbs_keccak')==1;s=s.replace('(* keep_hierarchy="yes" *) mhbs_keccak','// Permit LUT mapping across adjacent combinational rounds.\n        mhbs_keccak');p.write_text(s)
c=dict(label='round_flat',tag=tag,workspace=str(w),baseline='lut21k_20261002_v1_bank',code_sha256={str(p.relative_to(w)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ['rtl','tb','scripts','experiments','model','tests'] for p in (w/d).rglob('*') if p.is_file()})
out=r/'candidates'/tag;out.mkdir(parents=True);(out/'candidate.json').write_text(json.dumps(c,indent=2)+'\n');(out/'incremental.patch').write_text(''.join(difflib.unified_diff((root/rel).read_text().splitlines(True),s.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel)));cfg=json.loads((r/'config.json').read_text());cfg['candidates'].append(c);(r/'config.json').write_text(json.dumps(cfg,indent=2)+'\n');shutil.copy2('/tmp/prepare_round_flat.py',r/'prepare_round_flat.py')
print(w)
