open_checkpoint {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/kpu_atp_opt_20261007/c4b_shared_sponge_write/K1P4U1/post_synth.dcp}
set c [get_cells -quiet -hier -filter {REF_NAME =~ FD* && NAME =~ *sponge_state_reg*}]
puts "STATE_AUDIT c4b_shared_sponge_write [llength $c]"
close_design
exit
