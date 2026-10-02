reg parent_inputs_live=0;
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
