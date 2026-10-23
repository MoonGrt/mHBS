from pathlib import Path
from hashlib import sha256,shake_256
import subprocess,json
ROOT=Path.cwd();work=ROOT/'tmp/shake_p1_optimization_20261021'
tb=(ROOT/'tb/tb_recipe.sv').read_text().split(' logic [457:0] vectors')[0]
tb=tb.replace('module tb_recipe #','module tb_scalar_chain #')
tb=tb.replace(" logic [63:0] request_recipe;", " logic [63:0] request_recipe,step_recipe;\n logic [4:0] chain_steps,capture_after;")
tb=tb.replace(".request_step_recipe(64'd0)",'.request_step_recipe(step_recipe)').replace(".request_chain(1'b0),.request_steps(5'd0),.request_capture_after(5'd0)",".request_chain(1'b1),.request_steps(chain_steps),.request_capture_after(capture_after)")
tb+='''
 logic [575:0] vectors[0:2047];logic [19:0] leaf;
 string vector_file;integer count,timeout;
 longint unsigned baseline_hashes,baseline_perms,cycles;
 task automatic tick;@(posedge clk);#1;cycles++;endtask
 initial begin
  cycles=0;
  for(integer k=0;k<32;k++)begin
   secret_seed[k*8+:8]=8'(k+1);secret_prf[k*8+:8]=8'(k+33);public_seed[k*8+:8]=8'(k+65);
   root[k*8+:8]=8'(k+97);randomizer[k*8+:8]=8'(k+129);left[k*8+:8]=8'(k+161);right[k*8+:8]=8'(k+193);
  end
  for(integer k=0;k<16;k++)identifier[k*8+:8]=8'(k+225);
  message_buffer=0;message_length=1;capture_requested=1;
  if(!$value$plusargs("VECTOR=%s",vector_file) || !$value$plusargs("COUNT=%d",count))$fatal(1,"VECTOR/COUNT");
  $readmemh(vector_file,vectors);
  for(integer c=0;c<count;c++)begin
   request_valid=0;response_ready=0;
   if(c%2==0)begin rst=1;tick();tick();rst=0;end
   baseline_hashes=hashes;baseline_perms=permutations;
   chain_steps=vectors[c][516:512];capture_after=vectors[c][521:517];
   node_bytes=vectors[c][527:522];leaf=vectors[c][555:536];
   request_recipe={4'd0,4'd1,8'h83,8'd1,10'd0,6'd63,24'd0};
   step_recipe={4'd0,4'd2,vectors[c][535:528],8'd1,10'd0,6'd63,24'd0};
   tick();request_valid=1;tick();request_valid=0;timeout=0;
   while(!response_valid)begin tick();timeout++;if(timeout>10000 || error)$fatal(1,"case %0d timeout/error",c);end
   if(response_value[391:256]!==0 || response_value[255:0]!==vectors[c][255:0] || response_capture!==vectors[c][511:256])
    $fatal(1,"case %0d chain output/capture mismatch n=%0d steps=%0d cap=%0d leaf=%0d got=%h exp=%h capgot=%h capexp=%h",c,node_bytes,chain_steps,capture_after,leaf,response_value[255:0],vectors[c][255:0],response_capture,vectors[c][511:256]);
   if(hashes-baseline_hashes!=chain_steps+1 || permutations-baseline_perms!=chain_steps+1)$fatal(1,"chain count mismatch");
   repeat(1+c%5)begin tick();if(!response_valid || response_value[255:0]!==vectors[c][255:0])$fatal(1,"response hold");end
   response_ready=1;tick();response_ready=0;tick();
  end
  $display("SCALAR_CHAIN_PASS cases=%0d total_test_cycles=%0d",count,cycles);$finish;
 end
endmodule
`default_nettype wire
'''
(work/'tb_scalar_chain.sv').write_text(tb)
be=lambda v:v.to_bytes(4,'big')
sk,pub=bytes(range(1,33)),bytes(range(65,97))
vectors=[];cases=[]
for n in (16,24,32):
 for steps in (0,1,2,7,15):
  for cap in sorted({0,steps//2,steps}):
   for domain in (0x83,3):
    for leaf in (0,1024,1048575):
     def addr(dom,b):return b''.join(map(be,(3,0,0x01234567,0x89abcdef,dom,leaf,67,b)))
     value=shake_256(pub[:n]+addr(0x83,0x12345678)+sk[:n]).digest(32);capture=value if cap==0 else None
     for step in range(steps):
      value=shake_256(pub[:n]+addr(domain,0x12345678 if domain==3 else step)+value[:n]).digest(32)
      if cap==step+1:capture=value
     assert capture is not None
     value=int.from_bytes(value,'little') | int.from_bytes(capture,'little')<<256 |steps<<512 | cap<<517 |n<<522 | domain<<528|leaf<<536
     vectors.append(f'{value:0144x}\n');cases.append((n,steps,cap,domain,leaf))
vec=work/'scalar_chain.mem';vec.write_text(''.join(vectors))
for u in (1,2):
 obj=work/f'chain_P1U{u}'
 command=['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module','tb_scalar_chain','-GPIPELINE=1',f'-GUNROLL={u}','--Mdir',str(obj),'rtl/hash/keccak.sv','rtl/hash/shake-recipe.sv',str(work/'tb_scalar_chain.sv')]
 with (work/f'chain_P1U{u}_compile.log').open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
 result=subprocess.run([str(obj/'Vtb_scalar_chain'),f'+VECTOR={vec}',f'+COUNT={len(vectors)}'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 (work/f'chain_P1U{u}.log').write_text(result.stdout);print(result.stdout,end='');result.check_returncode()
(work/'chain_coverage.json').write_text(json.dumps(dict(passed=True,cases_per_config=len(cases),configs=['P1U1','P1U2'],node_bytes=[16,24,32],steps=[0,1,2,7,15],domains=[0x83,3],leaf=[0,1024,1048575],source_sha=sha256((ROOT/'rtl/hash/shake-recipe.sv').read_bytes()).hexdigest()),indent=2)+'\n')
