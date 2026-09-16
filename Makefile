PYTHON ?= python3
VERILATOR ?= verilator

.PHONY: test lint sim-lms sim-xmss sim-slh-dsa sim-slh-dsa-cycles test-autonomous-job \
	test-state-recovery synth-p1u1 synth-p2u2 synth-slh-dsa-full compare-unified-hbs-paper \
	check-standalone check-parallel-isolation reproduce artifact ci ci-core rtl-test rtl-keccak-test rtl-sha256-bounded-test rtl-shake-stream-cycle-test \
	rtl-shake-test rtl-shake-stream-test rtl-shake-chain-test rtl-treehash-test \
	rtl-treehash-h10-test rtl-treehash-dynamic-test rtl-tree-descriptor-dynamic-slice-test rtl-treehash-cache-test rtl-treehash-auth-provider-test \
	rtl-treehash-warm-cache-test \
	rtl-treehash-warm-auth-test rtl-tree-descriptor-test \
	rtl-state-manager-test rtl-scratchpad-test \
	rtl-agu-test rtl-affine-agu-test rtl-address-binding-test \
	rtl-scratch-load-test rtl-data-descriptor-test rtl-scratch-arbiter-test \
	rtl-data-slice-test rtl-data-v2-slice-test rtl-data-v2-fault-test rtl-lms-tree-parent-test rtl-xmss-tree-parent-test rtl-xmss-tree-push-slice-test \
	rtl-data-tree-slice-test rtl-slh-dsa-tree-parent-test \
	rtl-slh-dsa-job-stream-test \
	rtl-slh-dsa-prehash-test rtl-slh-dsa-full-test \
	rtl-xmss-wots-leaf-test rtl-xmss-wots-tree-slice-test \
	rtl-dynamic-loop-test \
	rtl-data-ops-test \
	rtl-tree-push-test \
	rtl-tree-push-adapter-test \
	rtl-tree-push-slice-test \
	rtl-output-stream-test rtl-output-stream-cycle-test \
	rtl-scratch-alu-test \
	rtl-base-w-test \
	rtl-digit-unpack-test \
	rtl-scratch-bitfield-test \
	rtl-descriptor-shake-test \
	rtl-xmss-sign-prehash-test \
	rtl-xmss-generic-leaf-test \
	rtl-xmss-generic-tree-h2-test \
	rtl-xmss-generic-tree-h10-test \
	rtl-static-p2-test \
	rtl-windowed-p2-test \
	rtl-randomized-f-p2-test \
	rtl-layout-expr-test \
	rtl-layout-descriptor-test \
	rtl-layout-expr-w288-snapshot-test \
	rtl-randomized-hash-test \
	rtl-randomized-chain-test \
	synth-control synth-keccak-u1 synth-keccak-u2 collect-control-ppa collect-keccak-ppa \
	synth-randomized-chain collect-randomized-chain-ppa \
	synth-layout-expr collect-layout-expr-ppa \
	synth-layout-expr32 collect-layout-expr32-ppa \
	synth-digit-unpack collect-digit-unpack-ppa \
	synth-treehash-cache-full synth-treehash-cache-subtree collect-treehash-cache-ppa \
	synth-treehash-warm-cache collect-treehash-warm-cache-ppa \
	synth-static-p2 collect-static-p2-ppa \
	synth-windowed-p2 collect-windowed-p2-ppa \
	synth-randomized-f-p2 collect-randomized-f-p2-ppa \
	collect-scratchpad-ppa \
	synth-scratchpad-full synth-scratchpad-min \
	rtl-lmots-image-test rtl-xmss-wots-tree-h10-test export-rtl-microcode export-xmss-layouts export-slh-dsa-layouts

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

lint:
	$(PYTHON) -m compileall -q model scripts experiments tests
	$(PYTHON) scripts/check_independence.py

sim-lms:
	$(PYTHON) scripts/run_lms_model.py

sim-xmss:
	$(PYTHON) scripts/run_xmss_sign_microcode.py
	$(PYTHON) scripts/run_xmss_verify_microcode.py

sim-slh-dsa:
	$(PYTHON) scripts/run_slh_dsa_keygen_microcode.py
	$(PYTHON) scripts/run_slh_dsa_sign_microcode.py

sim-slh-dsa-cycles:
	$(PYTHON) scripts/measure_slh_dsa_cycles.py

test-autonomous-job:
	$(PYTHON) scripts/run_lmots_model.py
	$(MAKE) rtl-test

test-state-recovery:
	$(PYTHON) -m unittest -v tests.test_state_manager

rtl-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_autonomous_control \
		-o build/iverilog/autonomous_control.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/hash_lane/micro_hbs_hash_latency_stub.sv \
		rtl/top/micro_hbs_job_latch.sv \
		rtl/top/micro_hbs_control_slice.sv \
		tb/integration/tb_micro_hbs_autonomous_control.sv
	vvp build/iverilog/autonomous_control.vvp
	iverilog -g2012 -Wall -s tb_micro_hbs_image_lock \
		-o build/iverilog/image_lock.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/hash_lane/micro_hbs_hash_latency_stub.sv \
		rtl/top/micro_hbs_job_latch.sv \
		rtl/top/micro_hbs_control_slice.sv \
		tb/unit/tb_micro_hbs_image_lock.sv
	vvp build/iverilog/image_lock.vvp

rtl-keccak-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_keccak_f1600 \
		-o build/iverilog/keccak_f1600.vvp \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		tb/unit/tb_micro_hbs_keccak_f1600.sv
	vvp build/iverilog/keccak_f1600.vvp

rtl-sha256-bounded-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_sha256_bounded \
		-o build/iverilog/sha256_bounded.vvp \
		rtl/hash_lane/micro_hbs_sha256_bounded.sv \
		tb/unit/tb_micro_hbs_sha256_bounded.sv
	vvp build/iverilog/sha256_bounded.vvp

rtl-shake-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_shake256_single_block \
		-o build/iverilog/shake256_single_block.vvp \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		tb/unit/tb_micro_hbs_shake256_single_block.sv
	vvp build/iverilog/shake256_single_block.vvp

rtl-shake-stream-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_shake256_stream \
		-o build/iverilog/shake256_stream.vvp \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/hash_lane/micro_hbs_shake256_stream.sv \
		tb/unit/tb_micro_hbs_shake256_stream.sv
	vvp build/iverilog/shake256_stream.vvp

rtl-shake-stream-cycle-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_shake256_stream_cycles \
		-o build/iverilog/shake256_stream_cycles.vvp \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_stream.sv \
		tb/unit/tb_micro_hbs_shake256_stream_cycles.sv
	vvp build/iverilog/shake256_stream_cycles.vvp

rtl-shake-chain-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_shake_chain_slice \
		-o build/iverilog/shake_chain_slice.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/composer/micro_hbs_shake_chain_adapter.sv \
		rtl/top/micro_hbs_shake_chain_slice.sv \
		tb/integration/tb_micro_hbs_shake_chain_slice.sv
	vvp build/iverilog/shake_chain_slice.vvp

rtl-descriptor-shake-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_descriptor_shake_slice \
		-o build/iverilog/descriptor_shake_slice.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/composer/micro_hbs_layout_descriptor_store.sv \
		rtl/composer/micro_hbs_layout_component_store.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/hash_lane/micro_hbs_shake256_stream.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		rtl/composer/micro_hbs_descriptor_shake_composer.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/top/micro_hbs_descriptor_shake_slice.sv \
		tb/integration/tb_micro_hbs_descriptor_shake_slice.sv
	vvp build/iverilog/descriptor_shake_slice.vvp

rtl-xmss-sign-prehash-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_xmss_sign_prehash_slice \
		-o build/iverilog/xmss_sign_prehash_slice.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/composer/micro_hbs_layout_descriptor_store.sv \
		rtl/composer/micro_hbs_layout_component_store.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_stream.sv \
		rtl/composer/micro_hbs_descriptor_shake_composer.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/top/micro_hbs_descriptor_shake_slice.sv \
		tb/integration/tb_micro_hbs_xmss_sign_prehash_slice.sv
	vvp build/iverilog/xmss_sign_prehash_slice.vvp

rtl-xmss-generic-leaf-test:
	mkdir -p build/verilator/xmss_generic_leaf
	$(VERILATOR) --binary --timing -O3 -Wno-fatal -Wno-TIMESCALEMOD \
		-Wno-WIDTH -Wno-CMPCONST \
		--top-module tb_micro_hbs_xmss_generic_leaf_slice \
		--Mdir build/verilator/xmss_generic_leaf -o xmss_generic_leaf_tb \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/composer/micro_hbs_layout_descriptor_store.sv \
		rtl/composer/micro_hbs_layout_component_store.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/hash_lane/micro_hbs_shake256_stream.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		rtl/composer/micro_hbs_descriptor_shake_composer.sv \
		rtl/agu/micro_hbs_affine_agu.sv \
		rtl/memory/micro_hbs_data_descriptor_store.sv \
		rtl/memory/micro_hbs_address_binding_store.sv \
		rtl/memory/micro_hbs_scratch_load.sv \
		rtl/memory/micro_hbs_scratch_alu.sv \
		rtl/output/micro_hbs_output_stream.sv \
		rtl/memory/micro_hbs_data_engine.sv \
		rtl/memory/micro_hbs_scratch_arbiter.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/treehash/micro_hbs_treehash_min.sv \
		rtl/treehash/micro_hbs_tree_push_adapter.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent_context.sv \
		rtl/top/micro_hbs_xmss_generic_leaf_slice.sv \
		tb/integration/tb_micro_hbs_xmss_generic_leaf_slice.sv
	build/verilator/xmss_generic_leaf/xmss_generic_leaf_tb

rtl-xmss-generic-tree-h2-test:
	mkdir -p build/verilator/xmss_generic_tree_h2
	$(VERILATOR) --binary --timing -O3 -Wno-fatal -Wno-TIMESCALEMOD \
		-Wno-WIDTH -Wno-CMPCONST \
		--top-module tb_micro_hbs_xmss_generic_tree_h2 \
		--Mdir build/verilator/xmss_generic_tree_h2 -o xmss_generic_tree_h2_tb \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/composer/micro_hbs_layout_descriptor_store.sv \
		rtl/composer/micro_hbs_layout_component_store.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/hash_lane/micro_hbs_shake256_stream.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		rtl/composer/micro_hbs_descriptor_shake_composer.sv \
		rtl/agu/micro_hbs_affine_agu.sv \
		rtl/memory/micro_hbs_data_descriptor_store.sv \
		rtl/memory/micro_hbs_address_binding_store.sv \
		rtl/memory/micro_hbs_scratch_load.sv \
		rtl/memory/micro_hbs_scratch_alu.sv \
		rtl/output/micro_hbs_output_stream.sv \
		rtl/memory/micro_hbs_data_engine.sv \
		rtl/memory/micro_hbs_scratch_arbiter.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/treehash/micro_hbs_treehash_min.sv \
		rtl/treehash/micro_hbs_tree_push_adapter.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent_context.sv \
		rtl/top/micro_hbs_xmss_generic_leaf_slice.sv \
		tb/integration/tb_micro_hbs_xmss_generic_tree_h2.sv
	build/verilator/xmss_generic_tree_h2/xmss_generic_tree_h2_tb

rtl-xmss-generic-tree-h10-test:
	mkdir -p build/verilator/xmss_generic_tree_h10
	$(VERILATOR) --binary --timing -O3 -Wno-fatal -Wno-TIMESCALEMOD \
		-Wno-WIDTH -Wno-CMPCONST -GTEST_TREE_HEIGHT=10 \
		--top-module tb_micro_hbs_xmss_generic_tree_h2 \
		--Mdir build/verilator/xmss_generic_tree_h10 -o xmss_generic_tree_h10_tb \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/composer/micro_hbs_layout_descriptor_store.sv \
		rtl/composer/micro_hbs_layout_component_store.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/hash_lane/micro_hbs_shake256_stream.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		rtl/composer/micro_hbs_descriptor_shake_composer.sv \
		rtl/agu/micro_hbs_affine_agu.sv \
		rtl/memory/micro_hbs_data_descriptor_store.sv \
		rtl/memory/micro_hbs_address_binding_store.sv \
		rtl/memory/micro_hbs_scratch_load.sv \
		rtl/memory/micro_hbs_scratch_alu.sv \
		rtl/output/micro_hbs_output_stream.sv \
		rtl/memory/micro_hbs_data_engine.sv \
		rtl/memory/micro_hbs_scratch_arbiter.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/treehash/micro_hbs_treehash_min.sv \
		rtl/treehash/micro_hbs_tree_push_adapter.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent_context.sv \
		rtl/top/micro_hbs_xmss_generic_leaf_slice.sv \
		tb/integration/tb_micro_hbs_xmss_generic_tree_h2.sv
	build/verilator/xmss_generic_tree_h10/xmss_generic_tree_h10_tb

rtl-treehash-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_treehash_min \
		-o build/iverilog/treehash_min.vvp \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/treehash/micro_hbs_treehash_min.sv \
		rtl/treehash/micro_hbs_tree_parent_shake.sv \
		tb/integration/tb_micro_hbs_treehash_min.sv
	vvp build/iverilog/treehash_min.vvp

rtl-treehash-h10-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_treehash_min_h10 \
		-o build/iverilog/treehash_min_h10.vvp \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/treehash/micro_hbs_treehash_min.sv \
		rtl/treehash/micro_hbs_tree_parent_shake.sv \
		tb/integration/tb_micro_hbs_treehash_min_h10.sv
	vvp build/iverilog/treehash_min_h10.vvp

rtl-treehash-dynamic-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_treehash_min_dynamic \
		-o build/iverilog/treehash_min_dynamic.vvp \
		rtl/treehash/micro_hbs_treehash_min_dynamic.sv \
		tb/unit/tb_micro_hbs_treehash_min_dynamic.sv
	vvp build/iverilog/treehash_min_dynamic.vvp

rtl-tree-descriptor-dynamic-slice-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_tree_descriptor_dynamic_slice \
		-o build/iverilog/tree_descriptor_dynamic_slice.vvp \
		rtl/treehash/micro_hbs_tree_descriptor_store.sv \
		rtl/treehash/micro_hbs_treehash_min_dynamic.sv \
		rtl/top/micro_hbs_tree_descriptor_dynamic_slice.sv \
		tb/integration/tb_micro_hbs_tree_descriptor_dynamic_slice.sv
	vvp build/iverilog/tree_descriptor_dynamic_slice.vvp

rtl-treehash-cache-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_treehash_cache_modes \
		-o build/iverilog/treehash_cache_modes.vvp \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/treehash/micro_hbs_treehash_min.sv \
		rtl/treehash/micro_hbs_tree_parent_shake.sv \
		rtl/treehash/micro_hbs_treehash_cache_store.sv \
		rtl/treehash/micro_hbs_treehash_cached.sv \
		tb/integration/tb_micro_hbs_treehash_cache_modes.sv
	vvp build/iverilog/treehash_cache_modes.vvp

rtl-treehash-auth-provider-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_treehash_auth_provider \
		-o build/iverilog/treehash_auth_provider.vvp \
		rtl/treehash/micro_hbs_treehash_cache_store.sv \
		rtl/treehash/micro_hbs_treehash_auth_provider.sv \
		tb/integration/tb_micro_hbs_treehash_auth_provider.sv
	vvp build/iverilog/treehash_auth_provider.vvp

rtl-treehash-warm-cache-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_treehash_warm_active_cache \
		-o build/iverilog/treehash_warm_active_cache.vvp \
		rtl/treehash/micro_hbs_treehash_warm_active_cache.sv \
		tb/integration/tb_micro_hbs_treehash_warm_active_cache.sv
	vvp build/iverilog/treehash_warm_active_cache.vvp

rtl-treehash-warm-auth-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_treehash_warm_auth_integration \
		-o build/iverilog/treehash_warm_auth_integration.vvp \
		rtl/treehash/micro_hbs_treehash_warm_active_cache.sv \
		rtl/treehash/micro_hbs_treehash_auth_provider.sv \
		tb/integration/tb_micro_hbs_treehash_warm_auth_integration.sv
	vvp build/iverilog/treehash_warm_auth_integration.vvp

rtl-state-manager-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_state_manager \
		-o build/iverilog/state_manager.vvp \
		rtl/state_manager/micro_hbs_state_manager.sv \
		tb/unit/tb_micro_hbs_state_manager.sv
	vvp build/iverilog/state_manager.vvp

rtl-scratchpad-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_scratchpad64 \
		-o build/iverilog/scratchpad64.vvp \
		rtl/memory/micro_hbs_scratchpad64.sv \
		tb/unit/tb_micro_hbs_scratchpad64.sv
	vvp build/iverilog/scratchpad64.vvp

rtl-agu-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_agu \
		-o build/iverilog/agu.vvp \
		rtl/agu/micro_hbs_agu.sv \
		tb/unit/tb_micro_hbs_agu.sv
	vvp build/iverilog/agu.vvp

rtl-affine-agu-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_affine_agu \
		-o build/iverilog/affine_agu.vvp \
		rtl/agu/micro_hbs_affine_agu.sv \
		tb/unit/tb_micro_hbs_affine_agu.sv
	vvp build/iverilog/affine_agu.vvp

rtl-address-binding-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_address_binding_store \
		-o build/iverilog/address_binding_store.vvp \
		rtl/memory/micro_hbs_address_binding_store.sv \
		tb/unit/tb_micro_hbs_address_binding_store.sv
	vvp build/iverilog/address_binding_store.vvp

rtl-tree-descriptor-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_tree_descriptor_store \
		-o build/iverilog/tree_descriptor_store.vvp \
		rtl/treehash/micro_hbs_tree_descriptor_store.sv \
		tb/unit/tb_micro_hbs_tree_descriptor_store.sv
	vvp build/iverilog/tree_descriptor_store.vvp

rtl-scratch-load-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_scratch_load \
		-o build/iverilog/scratch_load.vvp \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/memory/micro_hbs_scratch_load.sv \
		tb/unit/tb_micro_hbs_scratch_load.sv
	vvp build/iverilog/scratch_load.vvp

rtl-data-descriptor-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_data_descriptor_store \
		-o build/iverilog/data_descriptor_store.vvp \
		rtl/memory/micro_hbs_data_descriptor_store.sv \
		tb/unit/tb_micro_hbs_data_descriptor_store.sv
	vvp build/iverilog/data_descriptor_store.vvp

rtl-scratch-arbiter-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_scratch_arbiter \
		-o build/iverilog/scratch_arbiter.vvp \
		rtl/memory/micro_hbs_scratch_arbiter.sv \
		tb/unit/tb_micro_hbs_scratch_arbiter.sv
	vvp build/iverilog/scratch_arbiter.vvp

rtl-data-slice-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_data_slice \
		-o build/iverilog/data_slice.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/agu/micro_hbs_affine_agu.sv \
		rtl/memory/micro_hbs_data_descriptor_store.sv \
		rtl/memory/micro_hbs_scratch_load.sv \
		rtl/memory/micro_hbs_scratch_alu.sv \
		rtl/output/micro_hbs_output_stream.sv \
		rtl/memory/micro_hbs_scratch_arbiter.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/memory/micro_hbs_data_engine.sv \
		rtl/top/micro_hbs_data_slice.sv \
		tb/integration/tb_micro_hbs_data_slice.sv
	vvp build/iverilog/data_slice.vvp

rtl-data-v2-slice-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_data_v2_slice \
		-o build/iverilog/data_v2_slice.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/agu/micro_hbs_affine_agu.sv \
		rtl/memory/micro_hbs_data_descriptor_store.sv \
		rtl/memory/micro_hbs_address_binding_store.sv \
		rtl/memory/micro_hbs_scratch_load.sv \
		rtl/memory/micro_hbs_scratch_alu.sv \
		rtl/output/micro_hbs_output_stream.sv \
		rtl/memory/micro_hbs_data_engine.sv \
		rtl/memory/micro_hbs_scratch_arbiter.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/top/micro_hbs_data_v2_slice.sv \
	tb/integration/tb_micro_hbs_data_v2_slice.sv
	vvp build/iverilog/data_v2_slice.vvp

rtl-data-v2-fault-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_data_v2_faults \
		-o build/iverilog/data_v2_faults.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/agu/micro_hbs_affine_agu.sv \
		rtl/memory/micro_hbs_data_descriptor_store.sv \
		rtl/memory/micro_hbs_address_binding_store.sv \
		rtl/memory/micro_hbs_scratch_load.sv \
		rtl/memory/micro_hbs_scratch_alu.sv \
		rtl/output/micro_hbs_output_stream.sv \
		rtl/memory/micro_hbs_data_engine.sv \
		rtl/memory/micro_hbs_scratch_arbiter.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/top/micro_hbs_data_v2_slice.sv \
		tb/integration/tb_micro_hbs_data_v2_faults.sv
	vvp build/iverilog/data_v2_faults.vvp

rtl-lms-tree-parent-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_lms_tree_parent \
		-o build/iverilog/lms_tree_parent.vvp \
		rtl/hash_lane/micro_hbs_sha256_bounded.sv \
		rtl/treehash/micro_hbs_lms_tree_parent.sv \
		tb/unit/tb_micro_hbs_lms_tree_parent.sv
	vvp build/iverilog/lms_tree_parent.vvp

rtl-xmss-tree-parent-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_xmss_tree_parent \
		-o build/iverilog/xmss_tree_parent.vvp \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent.sv \
		tb/unit/tb_micro_hbs_xmss_tree_parent.sv
	vvp build/iverilog/xmss_tree_parent.vvp

rtl-slh-dsa-tree-parent-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_slh_dsa_tree_parent \
		-o build/iverilog/slh_dsa_tree_parent.vvp \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/treehash/micro_hbs_slh_dsa_tree_parent.sv \
		tb/unit/tb_micro_hbs_slh_dsa_tree_parent.sv
	vvp build/iverilog/slh_dsa_tree_parent.vvp

rtl-slh-dsa-job-stream-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_slh_dsa_job_stream_loader \
		-o build/iverilog/slh_dsa_job_stream_loader.vvp \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/top/micro_hbs_slh_dsa_job_stream_loader.sv \
		tb/integration/tb_micro_hbs_slh_dsa_job_stream_loader.sv
	vvp build/iverilog/slh_dsa_job_stream_loader.vvp

rtl-slh-dsa-prehash-test: rtl-slh-dsa-full-test

rtl-slh-dsa-full-test:
	mkdir -p build/verilator/slh_dsa_full
	$(VERILATOR) --binary --timing -O3 -Wno-fatal -Wno-TIMESCALEMOD \
		-Wno-WIDTH -Wno-CMPCONST \
		--top-module tb_micro_hbs_slh_dsa_prehash_slice \
		--Mdir build/verilator/slh_dsa_full -o slh_dsa_full_tb \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/composer/micro_hbs_layout_descriptor_store.sv \
		rtl/composer/micro_hbs_layout_component_store.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/hash_lane/micro_hbs_shake256_stream.sv \
		rtl/composer/micro_hbs_descriptor_shake_composer.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/memory/micro_hbs_scratch_bitfield_load.sv \
		rtl/memory/micro_hbs_bitfield_load_adapter.sv \
		rtl/composer/micro_hbs_layout_expr.sv \
		rtl/memory/micro_hbs_expr_load_adapter.sv \
		rtl/composer/micro_hbs_base_w_checksum.sv \
		rtl/memory/micro_hbs_base_w_load_adapter.sv \
		rtl/memory/micro_hbs_wide_shift_load_adapter.sv \
		rtl/agu/micro_hbs_affine_agu.sv \
		rtl/memory/micro_hbs_data_descriptor_store.sv \
		rtl/memory/micro_hbs_address_binding_store.sv \
		rtl/memory/micro_hbs_scratch_load.sv \
		rtl/memory/micro_hbs_scratch_alu.sv \
		rtl/output/micro_hbs_output_stream.sv \
		rtl/memory/micro_hbs_data_engine.sv \
		rtl/treehash/micro_hbs_treehash_min_dynamic.sv \
		rtl/treehash/micro_hbs_slh_dsa_tree_parent.sv \
		rtl/treehash/micro_hbs_slh_dsa_tree_adapter.sv \
		rtl/top/micro_hbs_slh_dsa_job_stream_loader.sv \
		rtl/top/micro_hbs_slh_dsa_prehash_slice.sv \
		tb/integration/tb_micro_hbs_slh_dsa_prehash_slice.sv
	build/verilator/slh_dsa_full/slh_dsa_full_tb

rtl-xmss-wots-leaf-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_xmss_wots_leaf \
		-o build/iverilog/xmss_wots_leaf.vvp \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		rtl/composer/micro_hbs_xmss_wots_leaf.sv \
		tb/unit/tb_micro_hbs_xmss_wots_leaf.sv
	vvp build/iverilog/xmss_wots_leaf.vvp

rtl-xmss-wots-tree-slice-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_xmss_wots_tree_slice \
		-o build/iverilog/xmss_wots_tree_slice.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		rtl/composer/micro_hbs_xmss_wots_leaf.sv \
		rtl/composer/micro_hbs_xmss_wots_leaf_scratch_adapter.sv \
		rtl/treehash/micro_hbs_treehash_min.sv \
		rtl/treehash/micro_hbs_tree_push_adapter.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent_context.sv \
		rtl/memory/micro_hbs_scratch_arbiter.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/top/micro_hbs_xmss_wots_tree_slice.sv \
		tb/integration/tb_micro_hbs_xmss_wots_tree_slice.sv
	vvp build/iverilog/xmss_wots_tree_slice.vvp

rtl-xmss-wots-tree-h10-test:
	mkdir -p build/verilator/xmss_wots_tree_h10
	$(VERILATOR) --binary --timing -O3 -Wno-fatal -Wno-TIMESCALEMOD \
		-Wno-WIDTH -Wno-CMPCONST \
		--top-module tb_micro_hbs_xmss_wots_tree_h10 \
		--Mdir build/verilator/xmss_wots_tree_h10 -o xmss_wots_tree_h10_tb \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		rtl/composer/micro_hbs_xmss_wots_leaf.sv \
		rtl/composer/micro_hbs_xmss_wots_leaf_scratch_adapter.sv \
		rtl/treehash/micro_hbs_treehash_min.sv \
		rtl/treehash/micro_hbs_tree_push_adapter.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent_context.sv \
		rtl/memory/micro_hbs_scratch_arbiter.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/top/micro_hbs_xmss_wots_tree_slice.sv \
		tb/integration/tb_micro_hbs_xmss_wots_tree_h10.sv
	build/verilator/xmss_wots_tree_h10/xmss_wots_tree_h10_tb

rtl-xmss-tree-push-slice-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_xmss_tree_push_slice \
		-o build/iverilog/xmss_tree_push_slice.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		rtl/treehash/micro_hbs_treehash_min.sv \
		rtl/treehash/micro_hbs_tree_push_adapter.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent_context.sv \
		rtl/top/micro_hbs_xmss_tree_push_slice.sv \
		tb/integration/tb_micro_hbs_xmss_tree_push_slice.sv
	vvp build/iverilog/xmss_tree_push_slice.vvp

rtl-data-tree-slice-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_data_tree_slice \
		-o build/iverilog/data_tree_slice.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/agu/micro_hbs_affine_agu.sv \
		rtl/memory/micro_hbs_data_descriptor_store.sv \
		rtl/memory/micro_hbs_scratch_load.sv \
		rtl/memory/micro_hbs_scratch_alu.sv \
		rtl/output/micro_hbs_output_stream.sv \
		rtl/memory/micro_hbs_data_engine.sv \
		rtl/memory/micro_hbs_scratch_arbiter.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		rtl/treehash/micro_hbs_treehash_min.sv \
		rtl/treehash/micro_hbs_tree_push_adapter.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent.sv \
		rtl/treehash/micro_hbs_xmss_tree_parent_context.sv \
		rtl/top/micro_hbs_data_tree_slice.sv \
		tb/integration/tb_micro_hbs_data_tree_slice.sv
	vvp build/iverilog/data_tree_slice.vvp

rtl-dynamic-loop-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_dynamic_loop \
		-o build/iverilog/dynamic_loop.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		tb/unit/tb_micro_hbs_dynamic_loop.sv
	vvp build/iverilog/dynamic_loop.vvp

rtl-data-ops-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_data_ops \
		-o build/iverilog/data_ops.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		tb/unit/tb_micro_hbs_data_ops.sv
	vvp build/iverilog/data_ops.vvp

rtl-tree-push-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_tree_push \
		-o build/iverilog/tree_push.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		tb/unit/tb_micro_hbs_tree_push.sv
	vvp build/iverilog/tree_push.vvp

rtl-tree-push-adapter-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_tree_push_adapter \
		-o build/iverilog/tree_push_adapter.vvp \
		rtl/treehash/micro_hbs_treehash_min.sv \
		rtl/treehash/micro_hbs_tree_push_adapter.sv \
		tb/unit/tb_micro_hbs_tree_push_adapter.sv
	vvp build/iverilog/tree_push_adapter.vvp

rtl-tree-push-slice-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_tree_push_slice \
		-o build/iverilog/tree_push_slice.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/treehash/micro_hbs_treehash_min.sv \
		rtl/treehash/micro_hbs_tree_parent_shake.sv \
		rtl/treehash/micro_hbs_tree_push_adapter.sv \
		rtl/top/micro_hbs_tree_push_slice.sv \
		tb/integration/tb_micro_hbs_tree_push_slice.sv
	vvp build/iverilog/tree_push_slice.vvp

rtl-output-stream-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_output_stream \
		-o build/iverilog/output_stream.vvp \
		rtl/output/micro_hbs_output_stream.sv \
		tb/unit/tb_micro_hbs_output_stream.sv
	vvp build/iverilog/output_stream.vvp

rtl-output-stream-cycle-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_output_stream_cycles \
		-o build/iverilog/output_stream_cycles.vvp \
		rtl/output/micro_hbs_output_stream.sv \
		tb/unit/tb_micro_hbs_output_stream_cycles.sv
	vvp build/iverilog/output_stream_cycles.vvp

rtl-scratch-alu-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_scratch_alu \
		-o build/iverilog/scratch_alu.vvp \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/memory/micro_hbs_scratch_alu.sv \
		tb/unit/tb_micro_hbs_scratch_alu.sv
	vvp build/iverilog/scratch_alu.vvp

rtl-lmots-image-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_lmots_program_image \
		-o build/iverilog/lmots_program_image.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		tb/integration/tb_micro_hbs_lmots_program_image.sv
	vvp build/iverilog/lmots_program_image.vvp

rtl-base-w-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_base_w_checksum \
		-o build/iverilog/base_w_checksum.vvp \
		rtl/composer/micro_hbs_base_w_checksum.sv \
		tb/unit/tb_micro_hbs_base_w_checksum.sv
	vvp build/iverilog/base_w_checksum.vvp

rtl-digit-unpack-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_digit_unpack \
		-o build/iverilog/digit_unpack.vvp \
		rtl/composer/micro_hbs_digit_unpack.sv \
		tb/unit/tb_micro_hbs_digit_unpack.sv
	vvp build/iverilog/digit_unpack.vvp

rtl-scratch-bitfield-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_scratch_bitfield_load \
		-o build/iverilog/scratch_bitfield_load.vvp \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/memory/micro_hbs_scratch_bitfield_load.sv \
		tb/unit/tb_micro_hbs_scratch_bitfield_load.sv
	vvp build/iverilog/scratch_bitfield_load.vvp

rtl-static-p2-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_static_p2_shake_batch \
		-o build/iverilog/static_p2_shake_batch.vvp \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/top/micro_hbs_static_p2_shake_batch.sv \
		tb/integration/tb_micro_hbs_static_p2_shake_batch.sv
	vvp build/iverilog/static_p2_shake_batch.vvp

rtl-windowed-p2-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_windowed_p2_shake_slice \
		-o build/iverilog/windowed_p2_shake_slice.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/memory/micro_hbs_dual_message_bank64.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/composer/micro_hbs_static_p2_window_adapter.sv \
		rtl/top/micro_hbs_windowed_p2_shake_slice.sv \
		tb/integration/tb_micro_hbs_windowed_p2_shake_slice.sv
	vvp build/iverilog/windowed_p2_shake_slice.vvp

rtl-randomized-f-p2-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_randomized_f_p2_slice \
		-o build/iverilog/randomized_f_p2_slice.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		rtl/top/micro_hbs_randomized_f_p2_slice.sv \
		tb/integration/tb_micro_hbs_randomized_f_p2_slice.sv
	vvp build/iverilog/randomized_f_p2_slice.vvp

rtl-layout-expr-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_layout_expr \
		-o build/iverilog/layout_expr.vvp \
		rtl/composer/micro_hbs_layout_expr.sv \
		rtl/composer/micro_hbs_ordered_pair.sv \
		tb/unit/tb_micro_hbs_layout_expr.sv
	vvp build/iverilog/layout_expr.vvp

rtl-layout-descriptor-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_layout_descriptor_store \
		-o build/iverilog/layout_descriptor_store.vvp \
		rtl/composer/micro_hbs_layout_descriptor_store.sv \
		tb/unit/tb_micro_hbs_layout_descriptor_store.sv
	vvp build/iverilog/layout_descriptor_store.vvp

rtl-layout-expr-w288-snapshot-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_layout_expr \
		-o build/iverilog/layout_expr_w288_rejected.vvp \
		rtl/composer/micro_hbs_layout_expr_w288_rejected.sv \
		rtl/composer/micro_hbs_ordered_pair.sv \
		tb/unit/tb_micro_hbs_layout_expr_w288_rejected.sv
	vvp build/iverilog/layout_expr_w288_rejected.vvp

rtl-randomized-hash-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_randomized_hash \
		-o build/iverilog/randomized_hash.vvp \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		tb/unit/tb_micro_hbs_randomized_hash.sv
	vvp build/iverilog/randomized_hash.vvp

rtl-randomized-chain-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_randomized_chain_slice \
		-o build/iverilog/randomized_chain_slice.vvp \
		rtl/sequencer/micro_hbs_program_store.sv \
		rtl/sequencer/micro_hbs_sequencer.sv \
		rtl/memory/micro_hbs_scratchpad64.sv \
		rtl/hash_lane/micro_hbs_keccak_f1600.sv \
		rtl/hash_lane/micro_hbs_shake256_single_block.sv \
		rtl/composer/micro_hbs_randomized_hash.sv \
		rtl/composer/micro_hbs_randomized_f_scratch_adapter.sv \
		rtl/top/micro_hbs_randomized_chain_slice.sv \
		tb/integration/tb_micro_hbs_randomized_chain_slice.sv
	vvp build/iverilog/randomized_chain_slice.vvp

synth-p1u1:
	@echo 'synth-p1u1: NOT IMPLEMENTED (Gate 8 is open)'; exit 2

synth-p2u2:
	@echo 'synth-p2u2: NOT IMPLEMENTED (Gate 8 is open)'; exit 2

synth-control:
	mkdir -p build/vivado/control_slice_p1
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/control_slice_p1/vivado.log \
		-source experiments/synth_control_slice.tcl

collect-control-ppa:
	$(PYTHON) experiments/collect_control_ppa.py

synth-keccak-u1:
	mkdir -p build/vivado/keccak_u1
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/keccak_u1/vivado.log \
		-source experiments/synth_keccak_lane.tcl -tclargs 1

synth-keccak-u2:
	mkdir -p build/vivado/keccak_u2
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/keccak_u2/vivado.log \
		-source experiments/synth_keccak_lane.tcl -tclargs 2

collect-keccak-ppa:
	$(PYTHON) experiments/collect_keccak_ppa.py

synth-randomized-chain:
	mkdir -p build/vivado/randomized_chain_p1u2
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/randomized_chain_p1u2/vivado.log \
		-source experiments/synth_randomized_chain_slice.tcl

collect-randomized-chain-ppa:
	$(PYTHON) experiments/collect_randomized_chain_ppa.py

synth-layout-expr:
	mkdir -p build/vivado/layout_expr
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/layout_expr/vivado.log \
		-source experiments/synth_layout_expr.tcl

collect-layout-expr-ppa:
	$(PYTHON) experiments/collect_layout_expr_ppa.py

synth-layout-expr32:
	mkdir -p build/vivado/layout_expr32
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/layout_expr32/vivado.log \
		-source experiments/synth_layout_expr32.tcl

collect-layout-expr32-ppa:
	$(PYTHON) experiments/collect_layout_expr32_ppa.py

synth-digit-unpack:
	mkdir -p build/vivado/digit_unpack
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/digit_unpack/vivado.log \
		-source experiments/synth_digit_unpack.tcl

collect-digit-unpack-ppa:
	$(PYTHON) experiments/collect_digit_unpack_ppa.py

synth-treehash-cache-full:
	mkdir -p build/vivado/treehash_cache_full_h10
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/treehash_cache_full_h10/vivado.log \
		-source experiments/synth_treehash_cache_store.tcl -tclargs 2 4 full_h10

synth-treehash-cache-subtree:
	mkdir -p build/vivado/treehash_cache_subtree_h4_h10
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/treehash_cache_subtree_h4_h10/vivado.log \
		-source experiments/synth_treehash_cache_store.tcl -tclargs 1 4 subtree_h4_h10

collect-treehash-cache-ppa:
	$(PYTHON) experiments/collect_treehash_cache_ppa.py

synth-treehash-warm-cache:
	mkdir -p build/vivado/treehash_warm_active_cache_h10w4
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/treehash_warm_active_cache_h10w4/vivado.log \
		-source experiments/synth_treehash_warm_active_cache.tcl

collect-treehash-warm-cache-ppa:
	$(PYTHON) experiments/collect_treehash_warm_active_cache_ppa.py

synth-static-p2:
	mkdir -p build/vivado/static_p2_u2_batch
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/static_p2_u2_batch/vivado.log \
		-source experiments/synth_static_p2_shake_batch.tcl

collect-static-p2-ppa:
	$(PYTHON) experiments/collect_static_p2_shake_batch_ppa.py

synth-windowed-p2:
	mkdir -p build/vivado/windowed_p2_u2_slice
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/windowed_p2_u2_slice/vivado.log \
		-source experiments/synth_windowed_p2_shake_slice.tcl

collect-windowed-p2-ppa:
	$(PYTHON) experiments/collect_windowed_p2_shake_slice_ppa.py

synth-randomized-f-p2:
	mkdir -p build/vivado/randomized_f_p2_u2_raw
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/randomized_f_p2_u2_raw/vivado.log \
		-source experiments/synth_randomized_f_p2_slice.tcl

synth-slh-dsa-full:
	mkdir -p build/vivado/slh_dsa_full
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/slh_dsa_full/vivado.log \
		-source experiments/synth_slh_dsa_prehash_slice.tcl

collect-randomized-f-p2-ppa:
	$(PYTHON) experiments/collect_randomized_f_p2_ppa.py

collect-scratchpad-ppa:
	$(PYTHON) experiments/collect_scratchpad_ppa.py

synth-scratchpad-full:
	mkdir -p build/vivado/scratchpad_full
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/scratchpad_full/vivado.log \
		-source experiments/synth_scratchpad.tcl -tclargs 8192 full

synth-scratchpad-min:
	mkdir -p build/vivado/scratchpad_min
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/scratchpad_min/vivado.log \
		-source experiments/synth_scratchpad.tcl -tclargs 84 min

compare-unified-hbs-paper:
	$(PYTHON) experiments/audit_workload.py
	$(PYTHON) experiments/project_xmss_cache_sign.py

export-rtl-microcode:
	$(PYTHON) scripts/export_rtl_microcode.py

export-xmss-layouts:
	$(PYTHON) scripts/export_xmss_layouts.py

export-slh-dsa-layouts:
	$(PYTHON) scripts/export_slh_dsa_layouts.py

ci-core: lint test sim-lms sim-xmss sim-slh-dsa sim-slh-dsa-cycles rtl-test rtl-keccak-test rtl-sha256-bounded-test rtl-shake-test \
	rtl-shake-stream-test rtl-shake-stream-cycle-test rtl-shake-chain-test rtl-descriptor-shake-test rtl-xmss-sign-prehash-test rtl-xmss-generic-leaf-test rtl-xmss-generic-tree-h2-test rtl-treehash-test \
	rtl-treehash-h10-test rtl-treehash-dynamic-test rtl-tree-descriptor-dynamic-slice-test rtl-treehash-cache-test rtl-treehash-auth-provider-test \
	rtl-treehash-warm-cache-test \
	rtl-treehash-warm-auth-test rtl-tree-descriptor-test \
	rtl-state-manager-test rtl-scratchpad-test \
	rtl-agu-test rtl-affine-agu-test rtl-address-binding-test \
	rtl-scratch-load-test rtl-data-descriptor-test rtl-scratch-arbiter-test \
	rtl-data-slice-test rtl-data-v2-slice-test rtl-data-v2-fault-test rtl-lms-tree-parent-test rtl-xmss-tree-parent-test rtl-xmss-tree-push-slice-test \
	rtl-data-tree-slice-test rtl-slh-dsa-tree-parent-test \
	rtl-slh-dsa-job-stream-test \
	rtl-slh-dsa-prehash-test \
	rtl-xmss-wots-leaf-test rtl-xmss-wots-tree-slice-test rtl-xmss-wots-tree-h10-test \
	rtl-dynamic-loop-test rtl-data-ops-test rtl-tree-push-test \
	rtl-tree-push-adapter-test rtl-tree-push-slice-test \
	rtl-output-stream-test rtl-output-stream-cycle-test rtl-scratch-alu-test rtl-lmots-image-test \
	rtl-base-w-test rtl-digit-unpack-test rtl-scratch-bitfield-test rtl-static-p2-test \
	rtl-windowed-p2-test \
	rtl-randomized-f-p2-test \
	rtl-randomized-hash-test \
	rtl-layout-expr-test rtl-layout-descriptor-test rtl-layout-expr-w288-snapshot-test \
	rtl-randomized-chain-test

check-standalone:
	$(PYTHON) scripts/check_standalone.py

check-parallel-isolation:
	$(PYTHON) scripts/check_parallel_isolation.py

ci: ci-core check-standalone

reproduce: ci compare-unified-hbs-paper

artifact:
	@echo 'artifact: NOT IMPLEMENTED (Gate 8 is open)'; exit 2
