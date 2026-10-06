// Frozen pre-specialization executor at LANES=1. ROMs and all traffic are
// independent ports; compare external events every cycle, including stalls.
wire [3:0] old_pa,old_ta;wire [9:0] old_da;
wire old_mr,old_vr,old_vp,old_ov,old_busy,old_done,old_kg,old_error;
wire [255:0] old_out;wire [5:0] old_bytes;wire [1:0] old_kind;
wire [15:0] old_code;wire [31:0] old_boot,old_kc,old_sc,old_hash,old_perm;
frozen_mhbs_common #(.LANES(1),.UNROLL(UNROLL),.PIPELINE(PIPELINE),.PROFILE_ENABLE(PROFILE_ENABLE)) frozen(
 .clk,.rst,.program_address(old_pa),.template_address(old_ta),.descriptor_addresses(old_da),
 .program_data(pm[old_pa]),.template_data(tm[old_ta]),.descriptor_data({dm[old_da[9:5]],dm[old_da[4:0]]}),
 .job_secret_seed,.job_secret_prf,.job_public_seed,.job_randomizer,.job_public_root,.job_identifier,.job_index,.job_operation,
 .message_length,.message_data,.message_valid,.message_ready(old_mr),
 .verify_valid,.verify_data,.verify_ready(old_vr),.verify_pass(old_vp),
 .out_valid(old_ov),.out_data(old_out),.out_bytes(old_bytes),.result_kind(old_kind),
 .busy(old_busy),.done(old_done),.keygen_done(old_kg),.error(old_error),.error_code(old_code),
 .boot_cycles(old_boot),.keygen_cycles(old_kc),.sign_cycles(old_sc),.hash_count(old_hash),.permutation_count(old_perm));
always @(negedge clk)if(!rst)begin
 if({message_ready,verify_ready,verify_pass,out_valid,busy,done,keygen_done,error,error_code,boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count}
 !=={old_mr,old_vr,old_vp,old_ov,old_busy,old_done,old_kg,old_error,old_code,old_boot,old_kc,old_sc,old_hash,old_perm})
  $fatal(1,"single-lane cycle equivalence state=%0d old=%0d cycle=%0d",dut.core.state,frozen.core.state,cycles);
 if(out_valid && {out_data,out_bytes,result_kind}!=={old_out,old_bytes,old_kind})$fatal(1,"single-lane output equivalence");
end
