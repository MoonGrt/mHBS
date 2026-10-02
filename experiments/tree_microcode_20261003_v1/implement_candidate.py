#!/usr/bin/env python3
"""Materialize experimental RTL only after the independent software gate passes."""
import hashlib,json,re,shutil,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'manifests/experiments/tree_microcode_20261003_v1'
WS=ROOT/'build/tree_microcode_20261003_v1'
gate=json.loads((OUT/'software/gate.json').read_text());assert gate['passed'] and gate['rtl_unchanged']
for name,h in gate['source_sha256'].items():assert hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()==h
if not WS.exists():
 WS.mkdir(parents=True)
 with tarfile.open(OUT/'baseline/source_snapshot.tar.gz') as f:f.extractall(WS,filter='data')
# Rebuild from frozen baseline on every invocation; never overwrite production RTL.
with tarfile.open(OUT/'baseline/source_snapshot.tar.gz') as t:
 s=t.extractfile('rtl/top/mhbs_hbs.sv').read().decode()
 top=t.extractfile('rtl/top/mhbs_top.sv').read().decode()
 for path in ['tb/integration/tb_mhbs_external.sv','tb/integration/tb_mhbs_verify.sv','tb/integration/mhbs_route_source_check.svh']:
  (WS/path).write_bytes(t.extractfile(path).read())

def replace(old,new):
 global s
 assert old in s,old[:100]
 s=s.replace(old,new)
def span(start,end,new):
 global s
 i=s.index(start);j=s.index(end,i);s=s[:i]+new+s[j:]
replace('// One ABI 4 SLH macro executor for n=16/24/32.','// ABI 5: ROM schedules node operations. No hardware TREE traversal.')
replace('output wire [3:0] program_address,','output wire [6:0] program_address,')
span('    typedef enum logic [5:0] {','    state_t state,', '''    typedef enum logic [5:0] {
        IDLE=0, MESSAGE=1, LAUNCH=2, FETCH=3, LOAD_DESCRIPTOR=4, DECODE=5,
        CHAIN_SETUP=7, CHAIN_STORE=8, CHAIN_OUTPUT0=10, CHAIN_OUTPUT1=11,
        CHAIN_NEXT=14, REDUCE_SETUP=15, LEAF_SETUP=16, NODE_HASH_DONE=19,
        HASH_ISSUE=22, HASH_WAIT=23, HASH_RESULT=24, ROUTE=25, TRANSFORM=26,
        EMIT=27, EMIT_NEXT=28, OUTPUT_CHUNK=29, DRAIN=30, FINISH=31, FAILED=32,
        VERIFY_INPUT=33, VERIFY_RANDOM=34, VERIFY_CHAIN_INPUT=35,
        VERIFY_CHAIN_RUN=36, VERIFY_CHAIN_ADVANCE=37
    } state_t;
''')
span('    logic seq_start, seq_complete;','    logic [4:0] chain_id', '''    logic [6:0] micro_pc,return_pc;
    logic return_valid;
    logic [31:0] scalar_temp;
    wire [7:0] uop=program_data[63:56], ua=program_data[55:48], ub=program_data[47:40], uc=program_data[39:32];
    wire [31:0] immediate=program_data[31:0];
    assign program_address=micro_pc;
    assign template_address=0;
''')
replace('logic standalone_chain, fors_pair_pending;','logic pair_pending;')
replace('logic [3:0] tree_height, node_level, auth_level;','logic [3:0] height_limit, node_level;')
replace('            TREE_INIT: hash_recipe_id={1\'b0,saved_descriptor[58:52]};\n','')
replace('            PARENT_SETUP: hash_recipe_id=parent_id;\n','')
replace('wire [255:0] parent_right = verifying && !node_index[0] ? emit_value : node_value;', 'wire [255:0] parent_right = node_value;')
replace('begin seq_complete<=1; enter_state(FETCH); end','begin enter_state(FETCH); end')
span('    // Validity is owned by the tree controller;','    integer i;', '''    // Explicit STORE instructions are the only writes to node scratch memories.
    always_ff @(posedge clk) begin
        if(!execution_rst && state==FETCH && uop==15) begin
            if(ua==0) stack[scalar_read(uc)[3:0]]<=node_read(ub);
            if(ua==1) auth_path[scalar_read(uc)[3:0]]<=node_read(ub);
        end
    end

    function automatic [4:0] desc_address(input [7:0] logical_address);
        case(logical_address)
          16:desc_address=12;17:desc_address=13;
          40:desc_address=16;41:desc_address=17;42:desc_address=18;43:desc_address=19;44:desc_address=20;
          48:desc_address=21;49:desc_address=22;50:desc_address=23;
          default:desc_address=logical_address[4:0];
        endcase
    endfunction
    function automatic [31:0] scalar_read(input [7:0] a);
        case(a)
          0:scalar_read={27'd0,layer};1:scalar_read={26'd0,group_index};
          2:scalar_read={18'd0,target};3:scalar_read={18'd0,leaf_cursor};
          4:scalar_read={18'd0,node_index};5:scalar_read={28'd0,node_level};
          6:scalar_read={28'd0,height_limit};7:scalar_read={27'd0,chain_id};
          8:scalar_read={27'd0,parent_id};10:scalar_read=scalar_temp;
          11:scalar_read={28'd0,macro_flags};12:scalar_read={31'd0,pair_pending};
          13:scalar_read={30'd0,indexing};16:scalar_read={22'd0,scalar_leaf};
          17:scalar_read={18'd0,fors_target(group_index)};18:scalar_read={30'd0,operation};
          20:scalar_read={28'd0,FORS_A};21:scalar_read={28'd0,HP};
          22:scalar_read=small_signature ? (profile_code==2 ? 8 : 7) : (profile_code==2 ? 17 : 22);
          23:scalar_read=small_signature ? (profile_code==0 ? 14 : profile_code==1 ? 17 : 22) : (profile_code==2 ? 35 : 33);
          default:scalar_read=0;
        endcase
    endfunction
    wire [31:0] scalar_a=scalar_read(ua),scalar_b=scalar_read(ub),scalar_c=scalar_read(uc);
    function automatic [255:0] node_read(input [7:0] a);
        case(a)
          0:node_read=node_value;1:node_read=task_left0;2:node_read=emit_value;
          3:node_read=result[0][255:0];4:node_read=result[1][255:0];
          default:node_read=0;
        endcase
    endfunction
    task automatic scalar_write(input [7:0] a,input [31:0] v);
        case(a)
          0:layer<=v[4:0];1:group_index<=v[5:0];2:target<=v[13:0];3:leaf_cursor<=v[13:0];
          4:node_index<=v[13:0];5:node_level<=v[3:0];6:height_limit<=v[3:0];
          7:chain_id<=v[4:0];8:parent_id<=v[4:0];10:scalar_temp<=v;
          11:macro_flags<=v[3:0];12:pair_pending<=v[0];13:indexing<=v[1:0];
          default:begin end
        endcase
    endtask
    task automatic node_write(input [7:0] a,input [255:0] v);
        case(a)
          0:node_value<=v;1:task_left0<=v;2:emit_value<=v;
          default:begin end
        endcase
    endtask

''')
# Slice function results using explicit read wires (portable SV).
s=s.replace('scalar_read(uc)[3:0]','scalar_c[3:0]')
replace('            seq_start<=0; seq_complete<=0;', '''            micro_pc<=0;return_pc<=0;return_valid<=0;scalar_temp<=0;
            chain_id<=0;parent_id<=0;height_limit<=0;node_level<=0;
            target<=0;leaf_cursor<=0;node_index<=0;indexing<=0;group_index<=0;''')
replace('            fors_pair_pending<=0;','            pair_pending<=0;')
replace('            done<=0; seq_start<=0; seq_complete<=0; abort_execution<=0;','            done<=0; abort_execution<=0;')
span('                LAUNCH: if(seq_ready)', '                LOAD_DESCRIPTOR:', '''                LAUNCH: begin micro_pc<=0;return_valid<=0;enter_state(FETCH);end
                FETCH: begin
                    micro_pc<=micro_pc+1'b1;
                    case(uop)
                      0:begin
                        if(verifying) verify_pass<=value[2][127:0]==job_public_root[127:0]
                          && (node_bytes==16 || value[2][191:128]==job_public_root[191:128])
                          && (node_bytes!=32 || value[2][255:192]==job_public_root[255:192]);
                        enter_state(DRAIN);
                      end
                      1:scalar_write(ua,immediate);
                      2:scalar_write(ua,scalar_b);
                      3:scalar_write(ua,scalar_b+immediate);
                      4:scalar_write(ua,scalar_b+scalar_c);
                      5:scalar_write(ua,scalar_b>>scalar_c);
                      6:scalar_write(ua,scalar_b<<scalar_c);
                      7:scalar_write(ua,scalar_b^immediate);
                      8:scalar_write(ua,scalar_b&immediate);
                      9:if(scalar_a==scalar_b)micro_pc<=immediate[6:0];
                      10:if(scalar_a!=scalar_b)micro_pc<=immediate[6:0];
                      11:micro_pc<=immediate[6:0];
                      12:begin return_pc<=micro_pc+1'b1;return_valid<=1;micro_pc<=immediate[6:0];end
                      13:begin micro_pc<=return_pc;return_valid<=0;end
                      14:begin
                        case(ub)
                          0:node_write(ua,stack[scalar_c[3:0]]);
                          1:node_write(ua,auth_path[scalar_c[3:0]]);
                          2:node_write(ua,value[scalar_c[1:0]]);
                          default:fail(16'h3006);
                        endcase
                      end
                      15:begin end // explicit scratch-memory write in the separate RAM process
                      16:node_write(ua,node_read(ub));
                      17:node_write(ua,256'd0);
                      18:start_output(node_read(ua),node_bytes,FETCH);
                      19:read_verify_node(FETCH); // INPUT IO, the sole external node latch
                      20,21,22,23,24:begin
                        macro_op<=uop==20 ? 1 : uop==21 ? 2 : uop==22 ? 6 : uop==23 ? 4 : 5;
                        macro_desc<=uop==21 ? desc_address({3'd0,chain_id}) : uop==22 ? parent_id : desc_address(ua);
                        macro_route<=uop==20 ? desc_address(ub) : 0;
                        task_chain<=0;task_capture<=0;
                        for(i=0;i<2;i=i+1)task_steps[i]<=0;
                        enter_state(LOAD_DESCRIPTOR);
                      end
                      25:begin macro_route<=desc_address(ua);route_result(ROUTE_NODE);end
                      default:fail(16'h3006);
                    endcase
                end
''')
span('                    2: begin\n                           chain_id', '                    4: begin checksum', '''                    2: begin
                           chain_cursor<=0;
                           endpoint_count<=descriptor[27:20];saved_chain_descriptor<=descriptor;enter_state(CHAIN_SETUP);
                       end
                    6: begin
                           task_leaf[0]<=indexing==1 ? scalar_leaf : 0;
                           task_a[0]<={3'd0,node_level};task_b[0]<=scalar_temp;
                           start_hash(saved_descriptor,2'b01,NODE_HASH_DONE);
                       end
''')
span('                TREE_INIT: begin','                CHAIN_SETUP: begin','')
replace('                    if(standalone_chain && chain_cursor==0)node_value<=result[0][W-1:0];\n','')
span('                    else if(standalone_chain && chain_descriptor[13:12]==0)', '                REDUCE_SETUP: begin', '''                    else if(!verifying && macro_flags[3] && leaf_cursor==target) begin
                        result[0]<=0;complete_macro();
                    end else if(chain_descriptor[13:12]==0)complete_macro();
                    else enter_state(REDUCE_SETUP);
                end
''')
span('                LEAF_SETUP: if(standalone_chain)', '                HASH_ISSUE: begin', '''                LEAF_SETUP: complete_macro();
                NODE_HASH_DONE: begin node_value<=result[0][W-1:0];complete_macro();end
''')
replace('                        seq_complete<=1;\n','')
# Remove stale commentary that describes a deleted tree FSM.
s=s.replace('    // Parent operands stay unchanged through HASH_ISSUE/HASH_WAIT and are\n    // updated only in PARENT_DONE. Other recipes do not consume the right\n    // input, so no duplicate parent-right register is needed.','    // Explicit node moves select operands before a HASH_PAIR instruction.\n    // Both operands remain stable until that single Hash finishes.')
assert not any(x in s for x in ('TREE_INIT','PUSH_NODE','PARENT_SETUP','PARENT_DONE','AUTH_OUTPUT','TREE_FINISH','standalone_chain','seq_start','seq_complete'))
(WS/'rtl/top/mhbs_hbs.sv').write_text(s)
top=top.replace('wire [3:0] program_address;','wire [6:0] program_address;').replace('program_memory[0:15]','program_memory[0:127]')
(WS/'rtl/top/mhbs_top.sv').write_text(top)
for filename in ['manifests/v42_sources.txt','manifests/unified_sources.txt']:
 p=WS/filename;s=p.read_text().replace('rtl/sequencer/mhbs_program_sequencer.sv\n','');p.write_text(s)
(WS/'rtl/sequencer/mhbs_program_sequencer.sv').unlink(missing_ok=True)
p=WS/'scripts/v42_common_partition.py';s=p.read_text().replace('output wire [3:0] program_address,','output wire [6:0] program_address,');p.write_text(s)
for name in ('slh_128f','slh_192f','slh_256f','slh_128s','slh_192s','slh_256s'):
 shutil.copytree(OUT/'software/images'/name,WS/'manifests/experiments/unified_hbs_v4.2/external_job_message/images'/name,dirs_exist_ok=True)
# New scoreboards check explicit node operands, independent from the old tree states.
(WS/'tb/integration/mhbs_parent_input_check.svh').write_text('''reg parent_inputs_live=0;
reg [255:0] parent_expected_left,parent_expected_right;
integer parent_input_cycles=0,parent_input_requests=0;
always @(posedge clk)begin
 if(`HBS_CORE.execution_rst)begin parent_inputs_live=0;parent_input_cycles=0;parent_input_requests=0;end
 else begin
  if(parent_inputs_live)begin
   if(`HBS_CORE.task_left0!==parent_expected_left || `HBS_CORE.parent_right!==parent_expected_right)
    $fatal(1,"microcode hash operand changed");
   parent_input_cycles=parent_input_cycles+1;
   if(`HBS_CORE.state==19)parent_inputs_live=0;
  end
  if(`HBS_CORE.state==5 && `HBS_CORE.macro_op==6)begin
   parent_expected_left=`HBS_CORE.task_left0;parent_expected_right=`HBS_CORE.node_value;
   parent_inputs_live=1;parent_input_requests=parent_input_requests+1;
  end
 end
end
task check_parent_input_coverage;
 begin
  if(!parent_input_requests || !parent_input_cycles || parent_inputs_live)$fatal(1,"parent coverage");
  $display("PARENT_INPUT_CHECK_PASS requests=%0d stable_cycles=%0d",parent_input_requests,parent_input_cycles);
 end
endtask
''')
p=WS/'tb/integration/mhbs_route_source_check.svh';s=p.read_text();i=s.index('   14:');j=s.index('   24:',i)
s=s[:i]+'''   3: if(`HBS_CORE.uop==25)begin route_expected={136'd0,`HBS_CORE.node_value};route_check_live=1;end
'''+s[j:];p.write_text(s)
p=WS/'tb/integration/tb_mhbs_verify.sv';s=p.read_text().replace('if(`HBS_CORE.state==18 /* PARENT_SETUP */)begin','if(`HBS_CORE.state==3 && `HBS_CORE.uop==19)begin');p.write_text(s)
p=WS/'tb/integration/tb_mhbs_external.sv';s=p.read_text().replace('reg [47:0] trace_expected','reg [63:0] trace_expected').replace('`HBS_CORE.cmd_valid','(`HBS_CORE.state==3)').replace('`HBS_CORE.cmd','`HBS_CORE.program_data');p.write_text(s)
# Freeze implementation artifacts separately from unchanged baseline.
(OUT/'candidate').mkdir(exist_ok=True)
for folder in ('rtl','tb','scripts','manifests'):
 if folder=='manifests':continue
 # Archive only changed or added files below to avoid copying unrelated evidence.
 baseline=json.loads((OUT/'baseline/inputs.json').read_text())['source_sha256']
 for p in (WS/folder).rglob('*'):
  if p.is_file() and p.suffix in ('.sv','.svh','.py'):
   rel=str(p.relative_to(WS));h=hashlib.sha256(p.read_bytes()).hexdigest()
   if baseline.get(rel)!=h:
    dest=OUT/'candidate'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
print('EXPERIMENTAL_RTL_READY',WS)
