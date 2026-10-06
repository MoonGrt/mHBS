`timescale 1ns/1ps
module tb_mhbs_s_parameters;
 logic clk=0,rst=1;
 logic [63:0] profile_descriptor=0;
 logic [127:0] descriptor_data=0;
 reg [391:0] digest;
 reg [255:0] expected_value[0:3];
 reg [63:0] expected_tail;
 reg [63:0] expected_tree;
 integer a,k,hp,tree_bits,fb,tb_bytes,lb,expected_leaf,expected_index;
 mhbs_hbs dut(.clk,.rst,.profile_descriptor,.descriptor_data,
  .job_valid(1'b0),.program_data(64'd0),.template_data(64'd0),
  .message_valid(1'b0),.verify_valid(1'b0));
 task automatic tick;
  #1;clk=1;#1;clk=0;#1;
 endtask
 // Exercise the actual clocked route, including destination isolation and
 // the no-store flag. Uninitialised data registers are deliberately retained.
 task automatic route_digest(input [1:0] slot,input bit discard,input bit parse);
  reg [63:0] control;
  begin
   control=0;control[57:56]=slot;control[53]=discard;control[54]=parse;
   descriptor_data={control,64'd0};
   dut.state=dut.ROUTE;dut.macro_route=1;dut.route_source=dut.ROUTE_HASH;dut.result=digest;
   if(!discard)begin
    expected_value[slot]=digest[255:0];
    if(slot==1)expected_tail=digest[319:256];
   end
   tick();
   for(integer slot_index=0;slot_index<4;slot_index=slot_index+1)
    if(dut.value[slot_index]!==expected_value[slot_index])
     $fatal(1,"route destination isolation slot=%0d written=%0d discard=%0d",slot_index,slot,discard);
   if(dut.fors_digest_tail!==expected_tail)$fatal(1,"FORS tail write isolation");
   if(dut.state!==dut.FETCH || !dut.seq_complete)$fatal(1,"route latency changed");
  end
 endtask
 initial begin
  tick();rst=0;
  // Populate all slots, then attempt suppressed writes with nonzero upper bits.
  for(integer slot=0;slot<4;slot=slot+1)begin
   for(integer j=0;j<49;j=j+1)digest[j*8 +:8]=$random;
   route_digest(2'(slot),0,0);
   digest=~digest;route_digest(2'(slot),1,0);
  end
  for(integer p=0;p<6;p=p+1)begin
   case(p)
    0:begin profile_descriptor=0;a=6;k=33;hp=3;tree_bits=63;end
    1:begin profile_descriptor=1;a=8;k=33;hp=3;tree_bits=63;end
    2:begin profile_descriptor=2;a=9;k=35;hp=4;tree_bits=64;end
    3:begin profile_descriptor=4;a=12;k=14;hp=9;tree_bits=54;end
    4:begin profile_descriptor=5;a=14;k=17;hp=9;tree_bits=54;end
    5:begin profile_descriptor=6;a=14;k=22;hp=8;tree_bits=56;end
   endcase
   fb=(a*k+7)/8;tb_bytes=(tree_bits+7)/8;lb=(hp+7)/8;
   // Walking bits cross both the 256-bit slot split and the 320-bit cutoff;
   // the final 72 Hmsg bits must still reach tree/leaf parsing on this cycle.
   // Replay after reset without clearing either the node or FORS-tail storage.
   rst=1;tick();rst=0;
   for(integer t=0;t<404;t=t+1)begin
    for(integer j=0;j<49;j=j+1)
     digest[j*8 +:8]=t==0 ? 0 : t==1 ? 255 : $random;
    if(t>=12)digest=392'd1<<(t-12);
    route_digest(1,0,1);
    for(integer g=0;g<k;g=g+1)begin
     expected_index=0;
     for(integer j=0;j<a;j=j+1)
      expected_index=(expected_index<<1)|int'(digest[((g*a+j)/8)*8+7-((g*a+j)%8)]);
     if(dut.fors_target(g)!==14'(expected_index))$fatal(1,"FORS decode profile=%0d group=%0d",p,g);
    end
    expected_tree=0;
    for(integer j=0;j<tb_bytes;j=j+1)expected_tree=(expected_tree<<8)|64'(digest[(fb+j)*8 +:8]);
    expected_tree=expected_tree & (~64'd0>>(64-tree_bits));
    expected_leaf=0;
    for(integer j=0;j<lb;j=j+1)expected_leaf=(expected_leaf<<8)|int'(digest[(fb+tb_bytes+j)*8 +:8]);
    expected_leaf=expected_leaf & ((1<<hp)-1);
    if(dut.parsed_tree(digest)!==expected_tree)$fatal(1,"tree decode profile=%0d",p);
    if(dut.parsed_leaf(digest)!==10'(expected_leaf))$fatal(1,"leaf decode profile=%0d expected=%0d",p,expected_leaf);
    if(dut.scalar_tree!==expected_tree || dut.scalar_leaf!==10'(expected_leaf))
     $fatal(1,"clocked Hmsg parse lost tail profile=%0d pattern=%0d",p,t);
   end
  end
  // A node-only tree result must zero-extend even after a dirty Hmsg route.
  digest='1;route_digest(3,0,0);
  dut.state=dut.TREE_FINISH;dut.operation=1;dut.macro_flags=8;
  tick();
  if(dut.route_value!=={136'd0,256'hffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff})
   $fatal(1,"tree root route retained non-node Hmsg bits");
  if(dut.state!==dut.ROUTE)$fatal(1,"tree finish latency changed");
  $display("S_PARAMETERS_PASS six_profiles all_FORS_groups zero_max_random walking_bits clocked_route isolation reset tree_leaf_endianness");$finish;
 end
endmodule
