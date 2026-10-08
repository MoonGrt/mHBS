#!/usr/bin/env python3
"""Cycle equivalence against the frozen pre-round-two chain formatter."""

if __name__ == "__main__":
    raise SystemExit("Pipeline support removed. Use scripts/run_lu_p1.py; historical experiments require their frozen source snapshots.")
import argparse,subprocess,tarfile,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);a=ap.parse_args();out=ROOT/a.out;out.mkdir(parents=True,exist_ok=True)
 archive=ROOT/'manifests/experiments/kpu_atp_unified_20261007/baseline/source_snapshot.tar.gz'
 with tarfile.open(archive) as t:source=t.extractfile('rtl/hash_lane/mhbs_chain_pipeline_lane.sv').read().decode()
 ref=out/'chain_ref.sv';ref.write_text(source.replace('module mhbs_chain_pipeline_lane #','module mhbs_chain_pipeline_lane_ref #'))
 records=[]
 for p in (1,2,3,4):
  binary=out/f'P{p}.vvp';log=out/f'P{p}.log'
  with log.open('w') as f:
   for cmd in (['iverilog','-g2012','-s','tb_mhbs_chain_format_equiv',f'-Ptb_mhbs_chain_format_equiv.PIPELINE={p}','-o',str(binary),'rtl/hash_lane/mhbs_chain_pipeline_lane.sv',str(ref),'tb/unit/tb_mhbs_chain_format_equiv.sv'],['vvp',str(binary)]):
    r=subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
    if r.returncode:raise RuntimeError(log.read_text()[-2000:])
  records.append({'p':p,'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()});print(log.read_text().splitlines()[-1],flush=True)
 (out/'results.json').write_text(json.dumps(records,indent=2)+'\n')
if __name__=='__main__':main()
