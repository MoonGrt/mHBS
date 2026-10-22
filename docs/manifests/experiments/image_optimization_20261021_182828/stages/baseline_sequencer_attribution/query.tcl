open_checkpoint /tmp/mhbs-image-soft-chain/build/soft_chain/20261021_173641/synthesis/shake/synthesized.dcp
set f [open /tmp/image_seq_audit/query.txt w]
foreach c [get_cells -hier -filter {NAME =~ core/sequencer/* && IS_PRIMITIVE == 1}] {
 puts $f "[get_property NAME $c] [get_property REF_NAME $c] [get_property ORIG_REF_NAME $c]"
}
close $f
exit
