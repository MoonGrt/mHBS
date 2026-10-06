"""Source snapshots and synthesis resource accounting for current P/U experiments."""
from pathlib import Path
import json,re,subprocess,tarfile
from v42_external_flow import ROOT,BASE,sha,write,rtl
PART='xc7a200tffg1156-3'
FREQ=150.0

def area(path):
 text=path.read_text();a={}
 for label,key in [('Slice LUTs','lut'),('Slice Registers','ff'),('LUT as Memory','lutram'),('Block RAM Tile','bram36'),('DSPs','dsp')]:
  m=re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d,.]+)',text);assert m,label;a[key]=float(m[1].replace(',',''))
 a['equivalent_slice']=a['lut']/4+a['ff']/8+232.4*a['bram36']+102.4*a['dsp'];return a

def snapshot(out):
 paths=set(rtl()+['manifests/v42_sources.txt','manifests/unified_sources.txt','Makefile','README.md','docs/Architecture.md','docs/Verification.md'])
 for directory in ('scripts','tb','model','tests','experiments/v4.2'):
  paths.update(str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*') if p.is_file() and p.suffix in ('.sv','.svh','.py','.tcl','.mem','.json'))
 for directory in ('images/slh_128f','vectors/slh_128f/sign'):
  paths.update(str(p.relative_to(ROOT)) for p in (BASE/directory).rglob('*') if p.is_file())
 identity={p:sha(ROOT/p) for p in sorted(paths)}
 if (out/'inputs.json').exists():assert json.loads((out/'inputs.json').read_text())['source_sha256']==identity,'Source changed: use fresh experiment tag'
 else:
  with tarfile.open(out/'source_snapshot.tar.gz','w:gz') as t:
   for p in identity:t.add(ROOT/p,arcname=p)
  write(out/'inputs.json',dict(git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_sha256=identity,snapshot_sha256=sha(out/'source_snapshot.tar.gz'),part=PART,clock_period_ns=6.666667,frequency_mhz_assumed=FREQ,profile_enable_synthesis=False,scope='common core',operation='128f sign',routed=False))
 return identity

