#!/usr/bin/env python3
"""Reproduce V7 recipe KATs from frozen RTL; does not run full Sign or Vivado."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,tarfile,tempfile
HERE=Path(__file__).resolve().parent
ARCHIVE=HERE.parents[1]
summary=json.loads((HERE/'VALIDATION.json').read_text())
for name,digest in json.loads((HERE/'SHA256.json').read_text()).items():
 assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest,'changed evidence: '+name
assert hashlib.sha256((ARCHIVE/'SOURCE.json').read_bytes()).hexdigest()==summary['frozen_binding']['SOURCE_manifest_sha256']
assert hashlib.sha256((ARCHIVE/'rtl.tar.gz').read_bytes()).hexdigest()==summary['frozen_binding']['rtl_tar_sha256']
with tempfile.TemporaryDirectory(prefix='mhbs_v7_recipe_') as temp:
 base=Path(temp)
 for group in summary['groups']:
  label=('shared' if group['shared_state'] else 'private')+'_P'+str(group['pipeline'])+'U'+str(group['unroll'])+('_synthesis' if group['synthesis'] else '')
  work=base/label;work.mkdir()
  with tarfile.open(ARCHIVE/'rtl.tar.gz') as tar:tar.extractall(work)
  recipe=work/'rtl/hash/shake-recipe.sv'
  assert hashlib.sha256(recipe.read_bytes()).hexdigest()==summary['candidate_sha256']
  for rel,digest in summary['KAT_support_files_match_frozen_manifest'].items():
   if rel.startswith('rtl/'): assert hashlib.sha256((work/rel).read_bytes()).hexdigest()==digest
  (work/'scripts').mkdir(exist_ok=True);(work/'tb').mkdir(exist_ok=True)
  shutil.copy2(HERE/'check_recipes.py',work/'scripts/check_recipes.py')
  tb=(HERE/'tb_recipe.sv').read_text()
  if not group['shared_state']:tb=tb.replace(".SHARED_STATE(1'b1)",".SHARED_STATE(1'b0)")
  (work/'tb/tb_recipe.sv').write_text(tb)
  assert hashlib.sha256((work/'tb/tb_recipe.sv').read_bytes()).hexdigest()==group['tb_sha256']
  command=[os.environ.get('PYTHON','python3'),str(work/'scripts/check_recipes.py'),'--pipeline',str(group['pipeline']),'--unroll',str(group['unroll'])]
  if group['synthesis']:command.append('--synthesis')
  print('Running '+label,flush=True)
  result=subprocess.run(command,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  print(result.stdout,end='');result.check_returncode()
  assert group['result_summary'] in result.stdout
  if label=='shared_P4U1':
   prefix=recipe.read_text().split('        end else begin : scheduled_execution')[0]
   assert hashlib.sha256(prefix.encode()).hexdigest()==summary['P1_scalar_prefix_sha256']
   lint=[os.environ.get('VERILATOR','verilator'),'--lint-only','--timing','--top-module','tb_recipe','-GPIPELINE=1','-GUNROLL=1','-Wno-fatal','rtl/hash/keccak.sv','rtl/hash/shake-recipe.sv','rtl/hash/sha256.sv','rtl/hash/sha2-recipe.sv','tb/tb_recipe.sv']
   check=subprocess.run(lint,cwd=work,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
   if check.returncode:print(check.stdout)
   check.check_returncode();print('P1U1 elaboration PASS; scalar source prefix unchanged',flush=True)
print('RECIPE_KAT_PASS groups=6 cases=2754; no full-core/Sign claim')
