"""Verify the isolated U2 counter transformation against baseline b4816c0."""
from pathlib import Path
import hashlib,json,re,subprocess,sys
root=Path(sys.argv[1] if len(sys.argv)>1 else '.').resolve()
commit='b4816c0c411f298bfd49f2f1f0885279683618bc'
def old(path):return subprocess.check_output(['git','show',f'{commit}:{path}'],cwd=root)
path='rtl/hash_lane/mhbs_compact_shake_context_lane.sv'
s=old(path).decode()
s=s.replace('    logic [4:0] round_index;',"    logic [3:0] pair_index;\n    wire [4:0] round_index = {pair_index, 1'b0};\n    wire last_pair = pair_index == 4'd11;")
s=re.sub(r'round_index\s*\+\s*UNROLL\s*>=\s*24','last_pair',s)
s=s.replace('round_index <= round_index + UNROLL;',"pair_index <= pair_index + 1'b1;")
s=re.sub(r"round_index <= ('0|0);","pair_index <= '0;",s)
s=s.replace('if (UNROLL < 1 || UNROLL > 24 || (24 % UNROLL) != 0)','if (UNROLL != 2)').replace('compact SHAKE lane UNROLL must divide 24','Production compact SHAKE lane requires U2')
assert s==(root/path).read_text()
unchanged={}
for p in (root/'manifests/v42_sources.txt').read_text().split():
 if p==path:continue
 data=(root/p).read_bytes();assert data==old(p),p
 unchanged[p]=hashlib.sha256(data).hexdigest()
for pair in range(12):
 assert ((pair*2+2)>=24)==(pair==11)
 if pair<11:assert pair*2+2==(pair+1)*2
print(json.dumps(dict(passed=True,baseline_commit=commit,changed_rtl=[path],
 other_rtl_byte_identical=True,keccak_hierarchy_and_constants_unchanged=True,
 unchanged_rtl_sha256=unchanged,reachable_counter_states_checked=12),indent=2))
