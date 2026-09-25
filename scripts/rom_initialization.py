#!/usr/bin/env python3
"""Transpose logical image words into fixed distributed-ROM INIT properties."""
from pathlib import Path
import argparse,json,sys,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model.profiles import PROFILES
from model.slh_only import SLH_PROFILES
from model.autonomous_hbs import ProgramImage
from model.physical_image import pack_template
BASE=ROOT/'manifests/experiments/unified_hbs_v4.1'
def mapping(name):
    result={}
    logical=ProgramImage.read(BASE/'images'/name)
    for kind,width,depth,ports,words in [('program',128,64,1,logical.program),('template',64,64,1,tuple(map(pack_template,logical.templates))),('descriptor',64,128,2,logical.descriptors)]:
        assert len(words)==depth and all(w.bit_length()<=width for w in words)
        for port in range(ports):
            columns=[sum(((word>>bit)&1)<<address for address,word in enumerate(words)) for bit in range(width)]
            # Exhaustive inverse mapping for every address and every physical replica.
            assert list(words)==[sum(((column>>address)&1)<<bit for bit,column in enumerate(columns)) for address in range(depth)]
            for bit,column in enumerate(columns):
                cell=f'{kind}_rom/port_bank[{port}].bit_cell[{bit}].depth{depth}.rom'
                result[cell]=f"{depth}'h{column:0{depth//4}x}"
    return result
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);parser.add_argument('--slh-only',action='store_true');args=parser.parse_args();args.directory.mkdir(parents=True,exist_ok=True)
    all_maps={name:mapping(name) for name in (SLH_PROFILES if args.slh_only else PROFILES)}
    for name,values in all_maps.items():
        # Exact names, including square brackets; braces avoid Tcl substitutions.
        commands=[]
        for cell,init in values.items():
            commands.append('set c [get_cells -quiet -hier -filter {NAME == "'+cell+'"}]')
            commands.append('if {[llength $c] != 1} {error {ROM cell missing: '+cell+'}}')
            commands.append('set_property INIT {'+init+'} $c')
        (args.directory/(name+'.tcl')).write_text('\n'.join(commands)+'\n')
    (args.directory/'mapping.json').write_text(json.dumps(all_maps,indent=2)+'\n')
    print('ROM_INIT_MAPPING_PASS',len(all_maps),'profiles',len(next(iter(all_maps.values()))),'physical cells per profile')
