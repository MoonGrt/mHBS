// Independent logical list scoreboard. Include inside either integration TB.
// Derive expected nodes from completed macros, not the physical write ports.
reg [255:0] shared_expected[0:67];
reg [67:0] shared_initialized=0;
reg shared_roots_live=0;
wire shared_stream_read =
 (`HBS_CORE.lanes[0].lane.state==2 && `HBS_CORE.lanes[0].lane.shapes[12] &&
  `HBS_CORE.lanes[0].lane.position>=`HBS_CORE.lanes[0].lane.prefix_bytes &&
  `HBS_CORE.lanes[0].lane.position<`HBS_CORE.lanes[0].lane.input_length) ||
 (`HBS_CORE.lanes[1].lane.state==2 && `HBS_CORE.lanes[1].lane.shapes[12] &&
  `HBS_CORE.lanes[1].lane.position>=`HBS_CORE.lanes[1].lane.prefix_bytes &&
  `HBS_CORE.lanes[1].lane.position<`HBS_CORE.lanes[1].lane.input_length);
always @(posedge clk) begin
 if(`HBS_CORE.execution_rst) begin
  shared_initialized=0; shared_roots_live=0;
 end else begin
  if(shared_stream_read) begin
   if(`HBS_CORE.endpoint_read0>=68 || !shared_initialized[`HBS_CORE.endpoint_read0])
    $fatal(1,"shared list read before write address=%0d",`HBS_CORE.endpoint_read0);
   for(integer b=0;b<32;b=b+1) if(b<`HBS_CORE.node_bytes)
    if(`HBS_CORE.endpoint_value0[b*8 +:8]!==shared_expected[`HBS_CORE.endpoint_read0][b*8 +:8])
     $fatal(1,"shared list mismatch address=%0d byte=%0d",`HBS_CORE.endpoint_read0,b);
  end
  if(`HBS_CORE.state==25 && `HBS_CORE.macro_route!=0 && `HBS_CORE.route_descriptor[53]) begin
   if(`HBS_CORE.group_index==0) shared_initialized=0;
   shared_roots_live=1;
   shared_expected[`HBS_CORE.group_index]=`HBS_CORE.route_value[255:0];
   shared_initialized[`HBS_CORE.group_index]=1;
  end
  if(`HBS_CORE.state==8) begin
   if(`HBS_CORE.indexing==1) begin
    if(`HBS_CORE.endpoint_write0 || `HBS_CORE.endpoint_write1)
     $fatal(1,"FORS leaf overwrites shared root storage");
   end else begin
    if(shared_roots_live) $fatal(1,"WOTS starts before FORS root compression completes");
    if(`HBS_CORE.chain_cursor==0) shared_initialized=0;
    for(integer i=0;i<2;i=i+1) if(`HBS_CORE.active_mask[i]) begin
     shared_expected[`HBS_CORE.chain_cursor+i]=`HBS_CORE.result[i][255:0];
     shared_initialized[`HBS_CORE.chain_cursor+i]=1;
    end
   end
  end
  if(`HBS_CORE.state==23 && `HBS_CORE.response_pending[0] && `HBS_CORE.lane_valid[0] &&
     `HBS_CORE.task_recipe[59:56]==12 && `HBS_CORE.task_recipe[55:48]==4) begin
   shared_roots_live=0; shared_initialized=0;
  end
 end
end
