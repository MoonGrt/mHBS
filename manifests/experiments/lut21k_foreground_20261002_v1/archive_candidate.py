import json,sys,shutil,hashlib
from pathlib import Path
r=Path(__file__).resolve().parent;root=r.parents[2];sys.path.insert(0,str(root/'scripts'));from optimize_lut21k import Driver,resources
label=sys.argv[1];c=next(x for x in json.loads((r/'config.json').read_text())['candidates'] if x['label']==label);tag=c['tag'];w=Path(c['workspace']);a=resources(w/'build/v4.2/external_job_message'/tag/'synthesis/core_utilization.rpt');d=object.__new__(Driver);d.run=r;d.state={'candidates':{tag:dict(status=sys.argv[2],core=a,pre_synth_checks_pass=True,core_synthesis_pass=True,full_regression_pass=False)}};d.archive(c);out=r/'candidates'/tag
for p in r.glob(label+'_*.log'):shutil.copy2(p,out/p.name)
for p in r.glob(label+'_*.json'):shutil.copy2(p,out/p.name)
(out/'evidence_sha256.json').write_text(json.dumps({str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name!='evidence_sha256.json'},indent=2)+'\n');print(tag,a)
