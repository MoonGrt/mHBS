#!/usr/bin/env python3
"""Preserve exploratory failures and interrupted runs without promoting their PPA."""
import json,shutil
from v42_flow import BUILD,BASE,sha,write
reasons={
 'compact_c0':'Early compact-format simulation; superseded before synthesis.',
 'compact_c1':'ROM inference mapping failed: construction truth tables lost address dependence.',
 'compact_c2':'Normal six images passed; extended standalone CHAIN mutation failed.',
 'compact_c2_route':'Interrupted after inherited standalone CHAIN error was detected; route not complete.',
 'feedback_reg_c0':'Compile failure from missing FEEDBACK state declaration; corrected in c1.',
 'hil64_c0':'Initial direct-absorb exploratory version; superseded by c1.',
}
for tag,reason in reasons.items():
 src=BUILD/tag
 if not src.exists():continue
 out=BASE/'attempts'/tag;out.mkdir(parents=True,exist_ok=True)
 for p in src.rglob('*'):
  rel=p.relative_to(src)
  if not p.is_file() or any(x in ('workspace','source') or x.startswith('obj') for x in rel.parts):continue
  if p.suffix not in ('.json','.log','.rpt','.tcl','.tsv','.txt','.gz','.dcp','.mem'):continue
  target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
 for p in BUILD.glob(tag+'*.log'):shutil.copy2(p,out/p.name)
 write(out/'attempt.json',dict(tag=tag,accepted=False,reason=reason))
 write(out/'evidence_sha256.json',{str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='evidence_sha256.json'})
# Local synth measurements belong to the source candidate, even when rejected.
for tag in ('hil64_c1','feedback_local_c0','feedback_reg_c1','ring_c0'):
 src=BUILD/tag;out=BASE/'candidates'/tag
 if not out.exists():continue
 for sub in ('local','hash_synth'):
  if (src/sub).exists():shutil.copytree(src/sub,out/sub,dirs_exist_ok=True)
print('V42_ATTEMPTS_ARCHIVED')
