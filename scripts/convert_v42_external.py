#!/usr/bin/env python3
"""Convert a layout-2 image into layout-3 microcode and external inputs."""
import argparse,sys
from pathlib import Path
from v42_external_flow import ROOT,PARAMS,sha,write
sys.path.insert(0,str(ROOT))
from model.slh64 import CompactImage
from model.slh64_external import convert_legacy
p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
image,job,root,msg,sign=convert_legacy(CompactImage.read(a.input));image.write(a.output)
cfg=dict(zip(PARAMS,[x.hex() for x in (job.secret,job.prf,job.public,job.random,root)]))
cfg.update(profile=f'slh_{len(root)*8}f',operation=int(sign),message_bytes=len(msg))
write(a.output/'job.json',cfg)
(a.output/'message.mem').write_text(''.join(f'{x:02x}\n' for x in msg))
write(a.output/'conversion.json',dict(format='slh64_v4.2',layout_revision=3,input_sha256={k:sha(a.input/k) for k in ('program.mem','template.mem','descriptor.mem')}))
print('EXTERNAL_CONVERSION_PASS')
