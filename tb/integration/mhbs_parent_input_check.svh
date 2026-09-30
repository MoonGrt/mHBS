// Freeze the old PARENT_SETUP operands in the testbench and compare the
// actual lane pins until PARENT_DONE, including request/response stalls.
// Reset/abort invalidates the scoreboard without clearing datapath storage.
localparam integer PARENT_PHYSICAL_LANE = SWAP ? 1 : 0;
reg parent_inputs_live=0;
reg [255:0] parent_expected_left,parent_expected_right;
integer parent_input_cycles=0,parent_input_requests=0;
integer parent_verify_left=0,parent_verify_right=0;
wire [255:0] parent_observed_left =
 `HBS_CORE.lanes[PARENT_PHYSICAL_LANE].lane.request_left;
wire [255:0] parent_observed_right =
 `HBS_CORE.lanes[PARENT_PHYSICAL_LANE].lane.request_right;
always @(posedge clk)begin
 if(`HBS_CORE.execution_rst)begin
  parent_inputs_live=0;parent_input_cycles=0;parent_input_requests=0;
  parent_verify_left=0;parent_verify_right=0;
 end else begin
  if(parent_inputs_live)begin
   // Controller states: HASH_ISSUE=22, HASH_WAIT=23, PARENT_DONE=19.
   if(`HBS_CORE.state!=22 && `HBS_CORE.state!=23 && `HBS_CORE.state!=19)
    $fatal(1,"parent hash left its request window unexpectedly");
   if(parent_observed_left!==parent_expected_left || parent_observed_right!==parent_expected_right)
    $fatal(1,"parent operand changed or reordered state=%0d index=%0d level=%0d",
     `HBS_CORE.state,`HBS_CORE.node_index,`HBS_CORE.node_level);
   parent_input_cycles=parent_input_cycles+1;
   if(`HBS_CORE.state==19)parent_inputs_live=0;
  end
  // PARENT_SETUP=18; signing can bypass the selected root's parent path.
  if(`HBS_CORE.state==18 && !(!`HBS_CORE.verifying && `HBS_CORE.macro_flags[3] &&
      (`HBS_CORE.node_index>>1)==(`HBS_CORE.target>>(`HBS_CORE.node_level+1))))begin
   if(`HBS_CORE.verifying)begin
    if(`HBS_CORE.node_index[0])begin
     parent_expected_left=`HBS_CORE.emit_value;
     parent_expected_right=`HBS_CORE.node_value;
     parent_verify_left=parent_verify_left+1;
    end else begin
     parent_expected_left=`HBS_CORE.node_value;
     parent_expected_right=`HBS_CORE.emit_value;
     parent_verify_right=parent_verify_right+1;
    end
   end else begin
    parent_expected_left=`HBS_CORE.stack[`HBS_CORE.node_level];
    parent_expected_right=`HBS_CORE.node_value;
   end
   parent_inputs_live=1;parent_input_requests=parent_input_requests+1;
  end
 end
end
task check_parent_input_coverage;
 begin
  if(parent_input_requests==0 || parent_input_cycles==0 || parent_inputs_live)
   $fatal(1,"parent operand coverage missing or unfinished");
  if(`HBS_CORE.verifying && (parent_verify_left==0 || parent_verify_right==0))
   $fatal(1,"verify parent operand ordering coverage missing");
  $display("PARENT_INPUT_CHECK_PASS requests=%0d stable_cycles=%0d auth_left=%0d auth_right=%0d",
   parent_input_requests,parent_input_cycles,parent_verify_left,parent_verify_right);
 end
endtask
