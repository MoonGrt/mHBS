import json,tarfile,shutil,difflib,hashlib
from pathlib import Path
root=Path.cwd();run=root/'manifests/experiments/lut21k_foreground_20261002_v1';base=Path('manifests/experiments/unified_hbs_v4.2/external_job_message');tag='lut21k_20261002_v1_route_alias';w=root/'build/v4.2/lut21k_workspaces'/tag
w.mkdir(exist_ok=False)
with tarfile.open(root/base/'candidates/lut21k_20261002_v1_bank/source_snapshot.tar.gz') as t:t.extractall(w,filter='data')
p=w/base/'candidates/parent_right_20260930_v1';p.mkdir(parents=True);shutil.copy2(root/base/'candidates/parent_right_20260930_v1/simulation.json',p/'simulation.json')
f=w/'rtl/top/mhbs_hbs.sv';old=f.read_text();s=old.replace('logic [V-1:0] result [0:1], route_value;','''logic [V-1:0] result [0:1];
    // ROUTE consumes these registers before it can update any source. Keep
    // the original staging cycle, but remember only the source selection.
    localparam logic [1:0] ROUTE_HASH=0, ROUTE_NODE=1, ROUTE_SAVED=2, ROUTE_EMIT=3;
    logic [1:0] route_source;
    wire [V-1:0] route_value = route_source==ROUTE_HASH ? result[0]
        : {{(V-W){1'b0}}, (route_source==ROUTE_NODE ? node_value
                        : route_source==ROUTE_SAVED ? value[3] : emit_value)};''')
s=s.replace('task automatic route_result(input [V-1:0] v);\n        begin route_value<=v; enter_state(ROUTE); end','task automatic route_result(input [1:0] source);\n        begin route_source<=source; enter_state(ROUTE); end')
s=s.replace("route_result({{(V-W){1'b0}},node_value})",'route_result(ROUTE_NODE)').replace('route_result(result[0])','route_result(ROUTE_HASH)').replace("route_result({{(V-W){1'b0}},emit_value})",'route_result(ROUTE_EMIT)')
s=s.replace("route_result({{(V-W){1'b0}},\n                    (!verifying && macro_flags[3] ? value[3] : node_value)})",'route_result(!verifying && macro_flags[3] ? ROUTE_SAVED : ROUTE_NODE)')
assert 'route_value<=' not in s;assert s.count('route_result(')==6;f.write_text(s)
check='''// Freeze the former route_result argument at its original capture edge.
// Compare at ROUTE consumption, before nonblocking updates to source registers.
reg route_check_live=0;
reg [391:0] route_expected;
integer route_checks=0;
always @(posedge clk) begin
 if(`HBS_CORE.execution_rst) begin route_check_live=0; route_checks=0; end
 else begin
  if(route_check_live) begin
   if(`HBS_CORE.state!=25 || `HBS_CORE.route_value!==route_expected)
    $fatal(1,"route source differs from frozen staging value state=%0d",`HBS_CORE.state);
   route_check_live=0; route_checks=route_checks+1;
  end
  case(`HBS_CORE.state)
   14: if(!(`HBS_CORE.indexing!=1 && `HBS_CORE.chain_cursor+2<`HBS_CORE.endpoint_count)
       && `HBS_CORE.standalone_chain && `HBS_CORE.chain_descriptor[13:12]==0) begin
    route_expected={136'd0,`HBS_CORE.node_value};route_check_live=1;
   end
   16: if(`HBS_CORE.standalone_chain) begin
    route_expected=`HBS_CORE.result[0];route_check_live=1;
   end
   21: begin
    route_expected={136'd0,(!`HBS_CORE.verifying && `HBS_CORE.macro_flags[3]
      ? `HBS_CORE.value[3] : `HBS_CORE.node_value)};route_check_live=1;
   end
   24: begin route_expected=`HBS_CORE.result[0];route_check_live=1;end
   34: begin route_expected={136'd0,`HBS_CORE.emit_value};route_check_live=1;end
  endcase
 end
end
task check_route_source_coverage;
 begin
  if(route_checks==0 || route_check_live)$fatal(1,"route source coverage missing");
  $display("ROUTE_SOURCE_CHECK_PASS checks=%0d",route_checks);
 end
endtask
'''
(w/'tb/integration/mhbs_route_source_check.svh').write_text(check)
for name in ['tb_mhbs_external.sv','tb_mhbs_verify.sv']:
 p=w/'tb/integration'/name;s=p.read_text().replace('`include "tb/integration/mhbs_parent_input_check.svh"','`include "tb/integration/mhbs_parent_input_check.svh"\n `include "tb/integration/mhbs_route_source_check.svh"').replace('check_parent_input_coverage();','check_parent_input_coverage();\n   check_route_source_coverage();');p.write_text(s)
out=run/'candidates'/tag;out.mkdir(parents=True)
patch=''
for rel in ['rtl/top/mhbs_hbs.sv','tb/integration/tb_mhbs_external.sv','tb/integration/tb_mhbs_verify.sv','tb/integration/mhbs_route_source_check.svh']:
 a=(root/rel).read_text() if (root/rel).exists() else '';b=(w/rel).read_text();patch+=''.join(difflib.unified_diff(a.splitlines(True),b.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
(out/'incremental.patch').write_text(patch)
code={str(p.relative_to(w)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ['rtl','tb','scripts','experiments','model','tests'] for p in (w/d).rglob('*') if p.is_file()}
c=dict(label='route_alias',tag=tag,workspace=str(w),code_sha256=code,baseline='lut21k_20261002_v1_bank')
(out/'candidate.json').write_text(json.dumps(c,indent=2)+'\n');cfg=json.loads((run/'config.json').read_text());cfg['candidates'].append(c);(run/'config.json').write_text(json.dumps(cfg,indent=2)+'\n')
(run/'promotion_guard.json').write_text(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ['rtl','tb'] for p in (root/d).rglob('*') if p.is_file()},indent=2)+'\n')
shutil.copy2('/tmp/prepare_route_alias.py',run/'prepare_route_alias.py');print(w)
