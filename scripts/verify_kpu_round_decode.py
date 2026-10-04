#!/usr/bin/env python3
"""Check every valid/invalid round decoding input against the frozen round."""
import argparse,subprocess,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);a=ap.parse_args();out=ROOT/a.out;out.mkdir(parents=True,exist_ok=True)
 source=ROOT/'rtl/hash_lane/mhbs_keccak.sv';specialized='ROUND_STRIDE' in source.read_text();records=[]
 for p in (1,2,3,4):
  binary=out/f'P{p}.vvp';log=out/f'P{p}.log'
  with log.open('w') as f:
   for cmd in (['iverilog','-g2012','-s','tb_mhbs_round_decode',f'-Ptb_mhbs_round_decode.STRIDE={p}',f'-Ptb_mhbs_round_decode.SPECIALIZED={int(specialized)}','-o',str(binary),str(source),'tb/unit/tb_mhbs_round_decode.sv'],['vvp',str(binary)]):
    r=subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
    if r.returncode:raise RuntimeError(log.read_text()[-2000:])
  hits=[x for x in log.read_text().splitlines() if 'ROUND_DECODE_PASS' in x];assert hits;print(*hits,flush=True)
  records.append(dict(stride=p,specialized=specialized,passed=True,log_sha256=sha(log)))
 (out/'results.json').write_text(json.dumps(dict(source_sha256=sha(source),tests=records),indent=2)+'\n')
if __name__=='__main__':main()
