// Freeze the former route_result argument at its original capture edge.
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
