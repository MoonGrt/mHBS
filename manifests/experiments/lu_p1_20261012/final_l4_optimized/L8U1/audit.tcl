set_param general.maxThreads 4
open_checkpoint {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lu_p1_20261012/final_l4_optimized/synth_L8U1/synth.dcp}

set stats [get_cells -hier -quiet -regexp {.*(boot_cycles_reg|keygen_cycles_reg|sign_cycles_reg|hash_count_reg|permutation_count_reg|hash_base_reg|permutation_base_reg|cycles_reg).*}]
puts "PROFILE_REGISTERS [llength $stats]"
if {[llength $stats]} { puts $stats; error "profiling registers remain" }
set lanes [get_cells -hier -quiet -filter {REF_NAME =~ mhbs_recipe_lane*}]
puts "LANE_INSTANCES [llength $lanes]"
set rounds [get_cells -hier -quiet -filter {REF_NAME =~ mhbs_keccak*}]
puts "ROUND_INSTANCES [llength $rounds]"
exit
