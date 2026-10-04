
 // Analysis-only counters, never included in synthesis or production RTL.
 integer pr_cycles=0,pr_reported=0;
 integer pr_state_cycles[0:63],pr_state_work[0:63];
 integer pr_class_cycles[0:8],pr_class_work[0:8],pr_class_zero[0:8];
 integer pr_hist[0:8],pr_lane_work[0:1],pr_stage_work[0:1][0:3];
 integer pr_lane_perm[0:1],pr_batch_perm[0:1],pr_normal_perm[0:1];
 integer pr_feedback_conflict[0:1],pr_recycle_cycles[0:1],pr_new_wait[0:1];
 integer pr_active[0:1];
 wire [PIPELINE-1:0] pr_work[0:1];
 wire [1:0] pr_bdone,pr_ndone,pr_again,pr_recycle,pr_accept,pr_response;
 for(genvar pl=0;pl<2;pl++)begin: pr_lanes
  if(pl<LANES)begin
   for(genvar ps=0;ps<PIPELINE;ps++)begin
    assign pr_work[pl][ps]=`HBS_CORE.lanes[pl].lane.stages[ps].source_valid;
   end
   assign pr_bdone[pl]=`HBS_CORE.lanes[pl].lane.batch_perm_done;
   assign pr_ndone[pl]=`HBS_CORE.lanes[pl].lane.permutation_complete;
   assign pr_again[pl]=`HBS_CORE.lanes[pl].lane.chain_pipeline.engine.again;
   assign pr_recycle[pl]=`HBS_CORE.lanes[pl].lane.recycle;
   assign pr_accept[pl]=`HBS_CORE.pipe_selected[pl] && `HBS_CORE.pipe_ready[pl];
   assign pr_response[pl]=`HBS_CORE.pipe_mode && `HBS_CORE.pipe_valid[pl];
  end else begin
   assign pr_work[pl]=0;assign pr_bdone[pl]=0;assign pr_ndone[pl]=0;
   assign pr_again[pl]=0;assign pr_recycle[pl]=0;assign pr_accept[pl]=0;assign pr_response[pl]=0;
  end
 end
 integer pr_ncycles[0:15],pr_nwork[0:15],pr_nrequests[0:15],pr_nabsorb[0:15],pr_nfeed[0:15],pr_nrun[0:15],pr_nwait[0:15];
 integer pr_in_normal=0,pr_shape;
 integer pr_kind,pr_slots,pr_work_now,pr_batch_id=0,pr_in_batch=0;
 integer pr_bc,pr_bw,pr_bissue,pr_bwait,pr_bt,pr_bp,pr_bkind;
 integer pr_first_done,pr_last_done,pr_last_accept;
 integer pr_hist_batch[0:8];
 integer pr_outside=0,pr_outside_cycles=0,pr_direct_count=0;
 always @(posedge clk)begin
  if(rst)begin
   pr_in_normal=0;
   for(integer n=0;n<16;n++)begin pr_ncycles[n]=0;pr_nwork[n]=0;pr_nrequests[n]=0;pr_nabsorb[n]=0;pr_nfeed[n]=0;pr_nrun[n]=0;pr_nwait[n]=0;end
   pr_cycles=0;pr_reported=0;pr_in_batch=0;pr_batch_id=0;
   for(integer s=0;s<64;s++)begin pr_state_cycles[s]=0;pr_state_work[s]=0;end
   for(integer c=0;c<9;c++)begin pr_class_cycles[c]=0;pr_class_work[c]=0;pr_class_zero[c]=0;pr_hist[c]=0;end
   for(integer l=0;l<2;l++)begin
    pr_lane_work[l]=0;pr_lane_perm[l]=0;pr_batch_perm[l]=0;pr_normal_perm[l]=0;
    pr_feedback_conflict[l]=0;pr_recycle_cycles[l]=0;pr_new_wait[l]=0;
    for(integer s=0;s<4;s++)pr_stage_work[l][s]=0;
   end
  end else if(!`HBS_CORE.rst && `HBS_CORE.state!=0 && `HBS_CORE.state!=32)begin
   pr_cycles++;
   pr_work_now=$countones(pr_work[0])+$countones(pr_work[1]);
   pr_slots=$countones(`HBS_CORE.pipe_expected_mask);
   // Classes 0=FORS batch; 1/2=WOTS full/tail; 3/4=shortened WOTS full/tail;
   // 5=ordinary parent request; 6=all list requests; 7=message request; 8=control.
   pr_kind=8;
   if(`HBS_CORE.pipe_mode)begin
    if(`HBS_CORE.indexing==1)pr_kind=0;
    else if(`HBS_CORE.macro_flags[3] && `HBS_CORE.leaf_cursor==`HBS_CORE.target)
     pr_kind=pr_slots==LANES*PIPELINE ? 3 : 4;
    else pr_kind=pr_slots==LANES*PIPELINE ? 1 : 2;
   end else if(`HBS_CORE.state==22 || `HBS_CORE.state==23)begin
    if(`HBS_CORE.hash_return==19)pr_kind=5;
    else if(`HBS_CORE.task_recipe[59:56]==12)pr_kind=6;
    else pr_kind=7;
   end
   if(`HBS_CORE.state==22 || `HBS_CORE.state==23)begin
    pr_shape=`HBS_CORE.task_recipe[59:56];
    if(!pr_in_normal)pr_nrequests[pr_shape]++;
    pr_in_normal=1;pr_ncycles[pr_shape]++;pr_nwork[pr_shape]+=pr_work_now;
    if(`HBS_CORE.lanes[0].lane.take_stream)pr_nabsorb[pr_shape]++;
    if(`HBS_CORE.lanes[0].lane.state==2 && `HBS_CORE.lanes[0].lane.stream_accept)pr_nfeed[pr_shape]++;
    if(`HBS_CORE.lanes[0].lane.hash_state==2)pr_nrun[pr_shape]++;
    if(`HBS_CORE.lanes[0].lane.hash_state==1)pr_nwait[pr_shape]++;
   end else pr_in_normal=0;
   pr_state_cycles[`HBS_CORE.state]++;pr_state_work[`HBS_CORE.state]+=pr_work_now;
   pr_class_cycles[pr_kind]++;pr_class_work[pr_kind]+=pr_work_now;
   if(pr_work_now==0)pr_class_zero[pr_kind]++;
   pr_hist[pr_work_now]++;
   for(integer l=0;l<LANES;l++)begin
    pr_lane_work[l]+=$countones(pr_work[l]);
    pr_batch_perm[l]+=integer'(pr_bdone[l]);pr_normal_perm[l]+=integer'(pr_ndone[l]);
    pr_lane_perm[l]+=integer'(pr_bdone[l])+integer'(pr_ndone[l]);
    if(`HBS_CORE.pipe_mode && pr_recycle[l])pr_recycle_cycles[l]++;
    if(`HBS_CORE.pipe_selected[l] && !`HBS_CORE.pipe_ready[l])pr_new_wait[l]++;
    if(`HBS_CORE.pipe_selected[l] && pr_again[l])pr_feedback_conflict[l]++;
    for(integer s=0;s<PIPELINE;s++)pr_stage_work[l][s]+=integer'(pr_work[l][s]);
   end
   if(`HBS_CORE.pipe_direct)pr_direct_count++;
   if(`HBS_CORE.pipe_mode)begin
    if(!pr_in_batch)begin
     pr_in_batch=1;pr_batch_id++;pr_bc=0;pr_bw=0;pr_bissue=0;pr_bwait=0;pr_bt=0;pr_bp=0;pr_bkind=pr_kind;
     pr_first_done=-1;pr_last_done=-1;pr_last_accept=-1;
     for(integer i=0;i<9;i++)pr_hist_batch[i]=0;
    end
    pr_bc++;pr_bw+=pr_work_now;pr_bt+=$countones(pr_accept);pr_bp+=$countones(pr_bdone);
    if(`HBS_CORE.state==38)pr_bissue++;else pr_bwait++;
    pr_hist_batch[pr_work_now]++;
    if(|pr_accept)pr_last_accept=pr_bc;
    if(|pr_response)begin if(pr_first_done<0)pr_first_done=pr_bc;pr_last_done=pr_bc;end
   end else if(pr_in_batch)begin
    $display("KP_BATCH id=%0d kind=%0d cycles=%0d work=%0d issue=%0d wait=%0d tasks=%0d permutations=%0d first_done=%0d last_done=%0d last_accept=%0d",pr_batch_id,pr_bkind,pr_bc,pr_bw,pr_bissue,pr_bwait,pr_bt,pr_bp,pr_first_done,pr_last_done,pr_last_accept);
    pr_in_batch=0;
   end
  end
  if(done && !pr_reported)begin
   pr_reported=1;
   $display("KP_TOTAL cycles=%0d batches=%0d work=%0d direct_cycles=%0d",pr_cycles,pr_batch_id,pr_lane_work[0]+pr_lane_work[1],pr_direct_count);
   for(integer n=0;n<16;n++)if(pr_nrequests[n])$display("KP_NORMAL shape=%0d requests=%0d cycles=%0d work=%0d absorb=%0d feed=%0d hash_run=%0d hash_wait_block=%0d",n,pr_nrequests[n],pr_ncycles[n],pr_nwork[n],pr_nabsorb[n],pr_nfeed[n],pr_nrun[n],pr_nwait[n]);
   for(integer s=0;s<64;s++)if(pr_state_cycles[s])$display("KP_STATE state=%0d cycles=%0d work=%0d",s,pr_state_cycles[s],pr_state_work[s]);
   for(integer c=0;c<9;c++)$display("KP_CLASS kind=%0d cycles=%0d work=%0d zero=%0d",c,pr_class_cycles[c],pr_class_work[c],pr_class_zero[c]);
   for(integer n=0;n<=LANES*PIPELINE;n++)$display("KP_OCCUPANCY active=%0d cycles=%0d",n,pr_hist[n]);
   for(integer l=0;l<LANES;l++)begin
    $display("KP_LANE lane=%0d work=%0d permutations=%0d batch_permutations=%0d normal_permutations=%0d recycle=%0d new_wait=%0d feedback_conflict=%0d",l,pr_lane_work[l],pr_lane_perm[l],pr_batch_perm[l],pr_normal_perm[l],pr_recycle_cycles[l],pr_new_wait[l],pr_feedback_conflict[l]);
    for(integer s=0;s<PIPELINE;s++)$display("KP_STAGE lane=%0d stage=%0d work=%0d",l,s,pr_stage_work[l][s]);
   end
  end
 end
