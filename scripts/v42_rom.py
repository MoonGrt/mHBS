#!/usr/bin/env python3
"""Exhaustively check inferred-ROM address/INIT mapping and generate patches."""
import json,re,sys,tarfile
from functools import lru_cache
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def words(path):return [int(w,16) for w in path.read_text().split()]
@lru_cache(None)
def source_words(folder,path):
 with tarfile.open(folder/'source_snapshot.tar.gz') as t:
  return [int(w,16) for w in t.extractfile(path).read().decode().split()]
def init_value(value):return int(value.split("'h")[1],16)
def load(folder):
 result=[]
 for line in (folder/'rom_mapping.tsv').read_text().splitlines():
  kind,port,bit,cell,abits,pins,init=line.split('\t')
  row=dict(kind=kind,port=int(port),bit=int(bit),cell=cell,abits=int(abits),pins=list(map(int,pins.split(','))),init=init_value(init))
  assert sorted(row['pins'])==list(range(row['abits']))
  ref=source_words(folder,f'experiments/v4.2/{kind}_construction.mem')
  assert encode(row,ref)==row['init'],row
  result.append(row)
 assert len(result)==256 and len({r['cell'] for r in result})==256
 return result
def encode(row,data):
 value=0
 for index in range(1<<row['abits']):
  address=sum(((index>>i)&1)<<b for i,b in enumerate(row['pins']))
  value|=((data[address]>>row['bit'])&1)<<index
 return value
def main():
 folder=Path(sys.argv[1]);mapping=load(folder);out=folder/'init';out.mkdir(exist_ok=True)
 all_images={}
 for profile in ('slh_128f','slh_192f','slh_256f'):
  for op in ('keygen','sign'):
   image=ROOT/'manifests/experiments/unified_hbs_v4.2/images'/profile/op
   data={k:source_words(folder,str((image/(k+'.mem')).relative_to(ROOT))) for k in ('program','template','descriptor')}
   patches=[];commands=[]
   for row in mapping:
    value=encode(row,data[row['kind']]);width=1<<row['abits']
    c=row['cell'];commands.append(f"set_property INIT {width}'h{value:0{width//4}x} [get_cells {{{c}}}]")
    patches.append(dict(cell=c,init=value))
    for address,word in enumerate(data[row['kind']]):
     index=sum(((address>>b)&1)<<i for i,b in enumerate(row['pins']))
     assert (value>>index)&1==(word>>row['bit'])&1
   name=profile+'_'+op
   (out/(name+'.tcl')).write_text('\n'.join(commands)+'\n');all_images[name]=patches
 (out/'mapping.json').write_text(json.dumps(dict(mapping=mapping,images=all_images,passed=True),indent=2)+'\n')
 print('V42_ROM_MAPPING_PASS',len(mapping),len(all_images))
if __name__=='__main__':main()
