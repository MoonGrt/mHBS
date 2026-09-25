#!/usr/bin/env python3
"""Exercise real Vivado RAM64X1S/RAM128X1S simulation models with all seven INIT maps."""
from pathlib import Path
import hashlib,json,shutil,subprocess
from autonomous_flow import ROOT,BASE,BUILD,sha,write,logic,logic_id
from rom_initialization import mapping
from model.profiles import PROFILES
out=BUILD/'physical_rom';out.mkdir(parents=True,exist_ok=True)
names=list(PROFILES)
lines=['`timescale 1ns/1ps','module tb_physical_rom;','reg clk=0;always #5 clk=~clk;reg [6:0] address=0;wire [13:0] da;','wire [127:0] pd[0:6],td[0:6];wire [127:0] dd[0:6];', 'reg [127:0] ep[0:447],et[0:447];reg [63:0] ed[0:895];', 'genvar g,p;generate for(p=0;p<2;p=p+1) begin: addresses assign da[p*7 +:7]=address+p;end', 'for(g=0;g<7;g=g+1) begin: images', 'uhbs_image_rom #(.WIDTH(128),.ADDRESS_BITS(6),.PORTS(1)) program_rom(.clk,.addresses(address[5:0]),.data(pd[g]));','uhbs_image_rom #(.WIDTH(128),.ADDRESS_BITS(6),.PORTS(1)) template_rom(.clk,.addresses(address[5:0]),.data(td[g]));','uhbs_image_rom #(.WIDTH(64),.ADDRESS_BITS(7),.PORTS(2)) descriptor_rom(.clk,.addresses(da),.data(dd[g]));','end endgenerate']
for i,name in enumerate(names):
 for cell,value in mapping(name).items():lines.append(f"defparam images[{i}].{cell.replace('/','.')}.INIT={value};")
lines+=['initial begin']
for i,name in enumerate(names):
 for kind,array,depth in [('program','ep',64),('template','et',64),('descriptor','ed',128)]:
  lines.append(f'$readmemh("manifests/experiments/unified_hbs_v4.1/images/{name}/{kind}.mem",{array},{i*depth},{(i+1)*depth-1});')
lines+=['for(integer a=0;a<128;a=a+1) begin address=a;#10;', 'for(integer g=0;g<7;g=g+1) begin','if(pd[g]!==ep[g*64+(a&63)] || td[g]!==et[g*64+(a&63)]) $fatal(1,"program/template INIT map g=%0d a=%0d",g,a);','for(integer p=0;p<2;p=p+1) if(dd[g][p*64 +:64]!==ed[g*128+((a+p)&127)]) $fatal(1,"descriptor replica INIT g=%0d p=%0d a=%0d",g,p,a);','end end','$display("PHYSICAL_ROM_INIT_PASS profiles=7 words=3584 replicas=2");$finish;end endmodule']
tb=out/'tb_physical_rom.sv';tb.write_text('\n'.join(lines)+'\n')
vendor=Path(shutil.which('vivado')).resolve().parents[1]/'data/verilog/src/unisims'
models=[vendor/'RAM64X1S.v',vendor/'RAM128X1S.v']
log=BASE/'unit'/logic_id(logic())/'physical_rom.log';log.parent.mkdir(parents=True,exist_ok=True)
with log.open('w') as f:
 subprocess.run(['iverilog','-g2012','-DSYNTHESIS','-s','tb_physical_rom','-o',str(out/'rom.vvp'),'rtl/memory/uhbs_image_rom.sv',str(tb),*map(str,models)],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
 subprocess.run(['vvp',str(out/'rom.vvp')],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
assert 'PHYSICAL_ROM_INIT_PASS' in log.read_text()
write(log.with_suffix('.json'),dict(passed=True,log_sha256=sha(log),rom_rtl_sha256=sha(ROOT/'rtl/memory/uhbs_image_rom.sv'),generator_sha256=sha(__file__),vendor_model_sha256={str(p):sha(p) for p in models},image_sha256={name:{kind:sha(BASE/'images'/name/(kind+'.mem')) for kind in ('program','template','descriptor')} for name in names}))
print('PHYSICAL_ROM_INIT_PASS')
