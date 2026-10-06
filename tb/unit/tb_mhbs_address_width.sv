`timescale 1ns/1ps
module tb_mhbs_address_width;
 logic clk=0,rst=1;
 logic [63:0] profile_descriptor=0;
 integer a,k,hp,group_number,leaf_number,node_number,height;
 integer checked=0;
 reg [63:0] expected0,global_node;
 mhbs_hbs dut(.clk,.rst,.profile_descriptor,.descriptor_data(128'd0),
  .job_valid(1'b0),.program_data(64'd0),.template_data(64'd0),
  .message_valid(1'b0),.verify_valid(1'b0));
 task automatic tick;
  #1;clk=1;#1;clk=0;#1;
 endtask
 task automatic check_b(input [63:0] b0);
  begin
   if(b0>=64'h100000)$fatal(1,"reference exceeds 20-bit bound");
   if(dut.task_b!==20'(b0))
    $fatal(1,"latched address mismatch expected=%h actual=%h",b0,dut.task_b);
   if(dut.lane.request_b!==b0[31:0])
    $fatal(1,"32-bit lane address or zero extension mismatch");
   if(dut.error)$fatal(1,"unexpected controller error");
   checked=checked+1;
  end
 endtask
 initial begin
  tick();rst=0;
  for(integer p=0;p<6;p=p+1)begin
   case(p)
    0:begin profile_descriptor=0;a=6;k=33;hp=3;end
    1:begin profile_descriptor=1;a=8;k=33;hp=3;end
    2:begin profile_descriptor=2;a=9;k=35;hp=4;end
    3:begin profile_descriptor=4;a=12;k=14;hp=9;end
    4:begin profile_descriptor=5;a=14;k=17;hp=9;end
    5:begin profile_descriptor=6;a=14;k=22;hp=8;end
   endcase
   rst=1;tick();rst=0;
   dut.macro_flags=0;dut.scalar_leaf=0;dut.chain_cursor=0;
   dut.endpoint_count=67;dut.saved_chain_descriptor=0;
   // All algorithm groups, plus the 6-bit field maximum as a conservative
   // bound. Exercise both boundary and randomized leaf indices.
   for(integer g=0;g<=k;g=g+1)begin
    group_number=g==k ? 63 : g;
    dut.group_index=6'(group_number);dut.indexing=1;dut.tree_height=4'(a);
    for(integer t=0;t<8;t=t+1)begin
     case(t)
      0:leaf_number=0;
      1:leaf_number=2;
      2:leaf_number=(1<<(a-1))-2;
      3:leaf_number=1<<(a-1);
      4:leaf_number=(1<<a)-2;
      default:leaf_number=($random & ((1<<a)-1)) & ~1;
     endcase
     dut.operation=1;dut.leaf_cursor=14'(leaf_number);dut.target=0;
     dut.state=dut.CHAIN_SETUP;tick();
     expected0=64'(group_number)*(64'd1<<a)+64'(leaf_number);
     check_b(expected0);
     if(dut.state!==dut.HASH_ISSUE)$fatal(1,"sign chain setup latency changed");
     // Verify accepts either parity, including the final leaf of a tree.
     dut.operation=2;dut.target=14'(leaf_number+(t&1));
     dut.state=dut.CHAIN_SETUP;tick();
     expected0=expected0+64'(t&1);check_b(expected0);
     if(dut.state!==dut.VERIFY_INPUT)$fatal(1,"verify setup latency changed");
    end
    for(integer level=0;level<a;level=level+1)
    for(integer t=0;t<4;t=t+1)begin
     case(t)
      0:node_number=0;
      1:node_number=1;
      2:node_number=(1<<(a-level))-1;
      default:node_number=$random & ((1<<(a-level))-1);
     endcase
     dut.operation=2;dut.node_level=4'(level);dut.node_index=14'(node_number);
     dut.state=dut.PARENT_SETUP;tick();
     // Independently compute the global node's parent in 64-bit arithmetic.
     global_node=64'(group_number)*(64'd1<<a)+64'(node_number)*(64'd1<<level);
     expected0=global_node/(64'd1<<(level+1));check_b(expected0);
     if(dut.state!==dut.HASH_ISSUE)$fatal(1,"FORS parent setup latency changed");
    end
   end
   // WOTS restore steps are four-bit values; upper address bits must clear.
   for(integer step=0;step<16;step=step+1)begin
    dut.operation=2;
    dut.task_b=20'hffff0|20'(step);
    dut.state=dut.VERIFY_CHAIN_ADVANCE;tick();
    check_b(64'((step+1)&15));
    if(dut.state!==dut.VERIFY_CHAIN_RUN)$fatal(1,"WOTS advance latency changed");
   end
  end
  // Exercise both non-FORS parent layouts through the existing clocked path.
  // Includes all supported XMSS heights and the full 14-level tree bound.
  for(integer mode=0;mode<2;mode=mode+1)
  for(height=1;height<=14;height=height+1)
  for(integer level=0;level<height;level=level+1)
  for(integer t=0;t<4;t=t+1)begin
   node_number=t==0 ? 0 : t==1 ? 1 : t==2 ? (1<<(height-level))-1 : $random & ((1<<(height-level))-1);
   dut.indexing=mode==0 ? 0 : 2;dut.operation=2;dut.macro_flags=0;
   dut.tree_height=4'(height);dut.node_level=4'(level);dut.node_index=14'(node_number);
   dut.state=dut.PARENT_SETUP;tick();
   expected0=64'(node_number)/2;
   if(mode)expected0=expected0+(64'd1<<(height-level-1));
   check_b(expected0);
   if(dut.state!==dut.HASH_ISSUE)$fatal(1,"XMSS/heap parent setup latency changed");
  end
  $display("ADDRESS_WIDTH_PASS cases=%0d six_profiles all_groups field_max leaf_bounds target_parity parent_levels zero_extend WOTS_wrap",checked);
  $finish;
 end
endmodule
