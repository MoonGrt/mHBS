import hashlib,json,subprocess,time
from pathlib import Path
p=Path(__file__).resolve().parent
sha=lambda n:hashlib.sha256(Path(n).read_bytes()).hexdigest()
source={n:sha(n) for n in Path('sources.txt').read_text().splitlines()}
s=Path('tb/tb_recipe.sv').read_text();s=s[:s.index('`ifdef SYNTHESIS\n // Count')]
s=s.replace('module tb_recipe #','module tb_scalar_batch #')
s=s.replace(' logic capture_requested=0;',' logic capture_requested=0;\n logic batch_mode=0,batch_valid=0,batch_ready=0;\n wire batch_accept,batch_done; wire [255:0] batch_digest;\n logic [19:0] leaf=0;')
s=s.replace(".batch_mode(1'b0),.batch_request_valid(1'b0),.batch_request_ready()",'.batch_mode,.batch_request_valid(batch_valid),.batch_request_ready(batch_accept)')
s=s.replace(".batch_fixed_shape(4'd0)",".batch_fixed_shape(4'd4)").replace(".batch_response_valid(),.batch_response_ready(1'b0)",'.batch_response_valid(batch_done),.batch_response_ready(batch_ready)').replace('.batch_response_digest(),','.batch_response_digest(batch_digest),')
m=bytes(range(1,6));h=hashlib.sha256(bytes(48)+m).digest();blocks=[hashlib.sha256(bytes(32)+h+i.to_bytes(4,'big')).digest() for i in [0,1]]
x=int.from_bytes(blocks[0]+blocks[1][:2],'little');y=int.from_bytes(blocks[0],'little')
s+='''
 task automatic tick;@(posedge clk);#1;endtask
 initial begin
  node_bytes=16;message_length=5;secret_seed=0;secret_prf=0;public_seed=0;root=0;randomizer=0;left=0;right=0;identifier=0;message_buffer=696'h0504030201;request_recipe=0;
  for(integer k=0;k<136;k++)nodes[k]=0;
  tick();tick();rst=0;
  for(integer c=0;c<3;c++)begin
   batch_mode=0;request_recipe=64'h0400000000000000;request_recipe[37:32]=c==1 ? 30 : 34;
   request_valid=1;#1;while(!request_ready)tick();tick();request_valid=0;
   while(!response_valid)tick();
   if(response_value!==((c==1) ? 392'hSHORT : 392'hLONG))$fatal(1,"scalar bytes c=%0d",c);
   response_ready=1;tick();response_ready=0;tick();
   batch_mode=1;batch_valid=1;#1;while(!batch_accept)tick();tick();batch_valid=0;
   while(!batch_done)tick();
   if(batch_digest!==256'hDIGEST || batch_hashes!=64'(2*(c+1)) || batch_permutations!=64'(3*(c+1)))$fatal(1,"batch after scalar length c=%0d",c);
   repeat(5)begin tick();if(!batch_done || batch_digest!==256'hDIGEST)$fatal(1,"batch stalled result");end
   batch_ready=1;tick();batch_ready=0;tick();
  end
  $display("SCALAR_BATCH_PASS 34/30/34 bytes; batch MGF only once; resetless replay and backpressure");$finish;
 end
 initial begin #1000000;$fatal(1,"timeout");end
endmodule
`default_nettype wire
'''.replace('SHORT',hex(int.from_bytes(blocks[0][:30],'little'))[2:]).replace('LONG',hex(x)[2:]).replace('DIGEST',hex(y)[2:])
tb=p/'tb_scalar_batch.sv';tb.write_text(s)
cmd=['verilator','--binary','--timing','-j','2','-Wno-fatal','-DMHBS_SHA2','--top-module','tb_scalar_batch','--Mdir',str(p/'obj_transition'),'rtl/hash/sha2-recipe.sv','rtl/hash/sha256.sv',str(tb)]
with (p/'transition_compile.log').open('w') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
assert r.returncode==0
r=subprocess.run([str(p/'obj_transition/Vtb_scalar_batch')],capture_output=True,text=True)
(p/'transition.log').write_text(r.stdout+r.stderr)
ok=r.returncode==0 and 'SCALAR_BATCH_PASS' in r.stdout
unchanged=all(sha(n)==v for n,v in source.items())
(p/'TRANSITION.json').write_text(json.dumps(dict(passed=ok,source_unchanged=unchanged,rtl_sha256=source,oracle='hashlib SHA256 H_msg and MGF1',command=cmd,log_sha256=sha(p/'transition.log'),testbench_sha256=sha(tb)),indent=2)+'\n')
print(r.stdout);assert ok and unchanged
