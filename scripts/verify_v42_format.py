#!/usr/bin/env python3
"""Fast offline image boundary checks; invalid images are outside the RTL contract."""
import sys
from dataclasses import replace
from pathlib import Path
from v42_flow import ROOT,BASE,NAMES,sha,write
sys.path.insert(0,str(ROOT))
from model.slh64 import CompactImage,TO_PHYSICAL
records=[]
for name in NAMES:
 image=CompactImage.read(BASE/'images'/name/'sign')
 def bad(label,field,index,value):
  words=list(getattr(image,field));words[index]=value
  try:replace(image,**{field:tuple(words)}).decode()
  except ValueError:records.append(name+'/'+label)
  else:raise AssertionError('accepted '+name+'/'+label)
 bad('profile_code','descriptors',1,3)
 bad('template_reference','templates',0,(image.templates[0]&~248)|(31<<3))
 bad('template_route','templates',0,(image.templates[0]&~7936)|(31<<8))
 bad('entry','program',52,image.program[52]^2)
 bad('zero_message','program',52,image.program[52]&63)
 bad('long_message','program',52,(image.program[52]&63)|(88<<6))
 bad('zero_repeat_loop','program',0,2<<62)
 bad('escaped_loop','program',0,(2<<62)|(31<<57)|(1<<51))
 bad('missing_halt','program',2,0)
 bad('instruction_reserved','program',31,1)
 bad('width','program',0,1<<64)
 bad('route_reference','descriptors',TO_PHYSICAL[17],(image.descriptors[TO_PHYSICAL[17]]&~(255<<36))|(31<<36))
 bad('ltree','descriptors',TO_PHYSICAL[17],(image.descriptors[TO_PHYSICAL[17]]&~(3<<12))|(2<<12))
 bad('leaf_hash','descriptors',TO_PHYSICAL[17],image.descriptors[TO_PHYSICAL[17]]|(2<<28))
 bad('endpoint_overflow','descriptors',TO_PHYSICAL[17],(image.descriptors[TO_PHYSICAL[17]]&~(255<<20))|(68<<20))
 image=CompactImage.read(BASE/'images'/name/'keygen')
 bad('keygen_root','program',48,1)
write(BASE/'format_gate.json',dict(passed=True,cases=records,driver_sha256=sha(Path(__file__)),model_sha256=sha(ROOT/'model/slh64.py')))
print('V42_FORMAT_GATE_PASS',len(records))
