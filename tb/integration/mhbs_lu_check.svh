// Test-only lane/bank lifetime checks. No production observation ports.
for(genvar q=0;q<LANES;q++)begin: lu_checks
 reg waiting=0;
 reg [63+64+1+5+5+1+10+8+32+256+256:0] saved_request;
 wire [63+64+1+5+5+1+10+8+32+256+256:0] request_fields={dut.core.task_recipe,dut.core.task_step,dut.core.task_chain,dut.core.task_steps[q],dut.core.task_capture_after[q],dut.core.task_capture[q],dut.core.task_leaf[q],dut.core.task_a[q],dut.core.task_b[q],dut.core.verify_chain_source?dut.core.result[q][255:0]:(q==0?dut.core.task_left0:256'd0),q==0?dut.core.parent_right:256'd0};
 always @(posedge clk)begin
  if(dut.core.execution_rst)waiting<=0;
  else begin
   if(q!=0 && dut.core.state==22 && dut.core.launch_pending[q] && dut.core.lane_ready[q])begin
    if((dut.core.task_recipe[59:56]==2 || dut.core.task_recipe[59:56]==8) && dut.core.task_recipe[47:40]!=1)
     $fatal(1,"independent lane received a multi-node recipe");
    if(dut.core.task_chain && (dut.core.task_step[59:56]==2 || dut.core.task_step[59:56]==8) && dut.core.task_step[47:40]!=1)
     $fatal(1,"independent lane received a multi-node chain step");
   end
   if(waiting && saved_request!==request_fields)$fatal(1,"lane request changed under backpressure %0d",q);
   waiting<=dut.core.state==22 && dut.core.launch_pending[q] && !dut.core.lane_ready[q];
   saved_request<=request_fields;
  end
 end
end
always @(posedge clk)if(!dut.core.execution_rst)begin
 if(dut.core.state==8 && dut.core.indexing!=1)begin
  if(dut.core.store_cursor>=LANES)$fatal(1,"store cursor out of range");
  if(dut.core.endpoint_write0 && dut.core.endpoint_address0[0])$fatal(1,"even bank parity");
  if(dut.core.endpoint_write1 && !dut.core.endpoint_address1[0])$fatal(1,"odd bank parity");
 end
 if(dut.core.fors_remaining!=0 && dut.core.fors_slot>=LANES)$fatal(1,"FORS slot overflow");
end
