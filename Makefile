PYTHON ?= python3
VERILATOR ?= verilator
JOBS ?= 8
VERILATOR_JOBS ?= $(JOBS)
VIVADO_TAG ?= slh_dsa_ratewide_v1
SLH_DSA_UNROLL ?= 2
HORIZONTAL_SIGN_TAG ?= horizontal_slh_dsa_sign
HORIZONTAL_SIGN_PART ?= xc7a200tffg1156-3
HORIZONTAL_SIGN_POSTROUTE_TAG ?= $(HORIZONTAL_SIGN_TAG)_postroute

SLH_DSA_RTL := \
	rtl/sequencer/micro_hbs_program_store.sv \
	rtl/sequencer/micro_hbs_sequencer.sv \
	rtl/composer/micro_hbs_layout_descriptor_store.sv \
	rtl/composer/micro_hbs_layout_component_store.sv \
	rtl/hash_lane/micro_hbs_keccak_f1600.sv \
	rtl/hash_lane/micro_hbs_shake256_single_block.sv \
	rtl/hash_lane/micro_hbs_shake256_stream.sv \
	rtl/composer/micro_hbs_rate_append64.sv \
	rtl/composer/micro_hbs_rate_append128.sv \
	rtl/composer/micro_hbs_hash_feedback_cache.sv \
	rtl/composer/micro_hbs_descriptor_shake_composer.sv \
	rtl/memory/micro_hbs_scratchpad64.sv \
	rtl/memory/micro_hbs_scratchpad64_banked.sv \
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
	rtl/top/micro_hbs_slh_dsa_top.sv \
	rtl/top/micro_hbs_slh_dsa_static_top.sv

.PHONY: test lint sim-lms sim-xmss sim-slh-dsa sim-slh-dsa-cycles \
	sim-slh-dsa-schedule compile-horizontal-slh-dsa compile-horizontal-contexts \
	test-state-recovery rtl-test rtl-unit-test rtl-keccak-test \
	rtl-sha256-bounded-test rtl-shake-test rtl-shake-stream-test \
	rtl-shake-stream-cycle-test rtl-state-manager-test rtl-scratchpad-test \
	rtl-horizontal-sequencer-test \
	rtl-horizontal-token-sequencer-test \
	rtl-horizontal-hash-lanes-test \
	rtl-horizontal-keccak-lanes-test \
	rtl-horizontal-shake-context-test \
	rtl-compact-shake-context-test \
	rtl-horizontal-slh-dsa-sign-test \
	rtl-affine-agu-test rtl-address-binding-test rtl-scratch-load-test \
	rtl-data-descriptor-test rtl-lms-tree-parent-test rtl-xmss-tree-parent-test \
	rtl-slh-dsa-tree-parent-test rtl-slh-dsa-job-stream-test \
	rtl-dynamic-loop-test rtl-data-ops-test rtl-output-stream-test \
	rtl-output-stream-cycle-test rtl-scratch-alu-test rtl-base-w-test \
	rtl-scratch-bitfield-test rtl-randomized-hash-test rtl-layout-expr-test \
	rtl-layout-descriptor-test rtl-rate-append-test rtl-treehash-dynamic-test \
	rtl-rate-append128-test rtl-banked-scratchpad-test rtl-feedback-cache-test \
	rtl-slh-dsa-full-test rtl-slh-dsa-full-profile rtl-slh-dsa-static-test \
	export-rtl-microcode export-xmss-layouts export-slh-dsa-layouts \
	synth-keccak-u1 synth-keccak-u2 collect-keccak-ppa synth-layout-expr32 \
	collect-layout-expr32-ppa synth-scratchpad-full synth-scratchpad-min \
	collect-scratchpad-ppa synth-slh-dsa-full compare-unified-hbs-paper \
	synth-slh-dsa-static-full synth-horizontal-hash-core \
	synth-horizontal-token-hash-core synth-horizontal-slh-dsa-sign \
	post-route-horizontal-slh-dsa-sign \
	check-standalone check-parallel-isolation ci-core ci reproduce artifact

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

lint:
	$(PYTHON) -m compileall -q model scripts experiments tests
	$(PYTHON) scripts/check_independence.py

sim-lms:
	$(PYTHON) scripts/run_lms_model.py
	$(PYTHON) scripts/run_lms_sign_verify_microcode.py

sim-xmss:
	$(PYTHON) scripts/run_xmss_sign_microcode.py
	$(PYTHON) scripts/run_xmss_verify_microcode.py

sim-slh-dsa:
	$(PYTHON) scripts/run_slh_dsa_keygen_microcode.py
	$(PYTHON) scripts/run_slh_dsa_sign_microcode.py
	$(PYTHON) scripts/run_slh_dsa_verify_microcode.py

sim-slh-dsa-schedule:
	$(PYTHON) scripts/simulate_slh_dsa_hash_schedule.py \
		--json-out manifests/experiments/slh_dsa_hash_schedule_v0.1.0.json \
		--trace-dir build/schedules/slh_dsa_kxu

compile-horizontal-slh-dsa:
	$(PYTHON) scripts/compile_slh_dsa_horizontal_microcode.py

compile-horizontal-contexts:
	$(PYTHON) scripts/compile_slh_dsa_horizontal_contexts.py

sim-slh-dsa-cycles:
	$(PYTHON) scripts/measure_slh_dsa_cycles.py

test-state-recovery:
	$(PYTHON) -m unittest -v tests.test_state_manager

rtl-keccak-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_keccak_f1600 -o build/iverilog/keccak_f1600.vvp rtl/hash_lane/micro_hbs_keccak_f1600.sv tb/unit/tb_micro_hbs_keccak_f1600.sv
	vvp build/iverilog/keccak_f1600.vvp

rtl-sha256-bounded-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_sha256_bounded -o build/iverilog/sha256_bounded.vvp rtl/hash_lane/micro_hbs_sha256_bounded.sv tb/unit/tb_micro_hbs_sha256_bounded.sv
	vvp build/iverilog/sha256_bounded.vvp

rtl-shake-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_shake256_single_block -o build/iverilog/shake256_single_block.vvp rtl/hash_lane/micro_hbs_keccak_f1600.sv rtl/hash_lane/micro_hbs_shake256_single_block.sv tb/unit/tb_micro_hbs_shake256_single_block.sv
	vvp build/iverilog/shake256_single_block.vvp

rtl-shake-stream-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_shake256_stream -o build/iverilog/shake256_stream.vvp rtl/hash_lane/micro_hbs_keccak_f1600.sv rtl/hash_lane/micro_hbs_shake256_single_block.sv rtl/hash_lane/micro_hbs_shake256_stream.sv tb/unit/tb_micro_hbs_shake256_stream.sv
	vvp build/iverilog/shake256_stream.vvp

rtl-shake-stream-cycle-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_shake256_stream_cycles -o build/iverilog/shake256_stream_cycles.vvp rtl/hash_lane/micro_hbs_keccak_f1600.sv rtl/hash_lane/micro_hbs_shake256_stream.sv tb/unit/tb_micro_hbs_shake256_stream_cycles.sv
	vvp build/iverilog/shake256_stream_cycles.vvp

rtl-horizontal-sequencer-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_horizontal_sequencer -o build/iverilog/horizontal_sequencer.vvp rtl/sequencer/micro_hbs_event_scoreboard.sv rtl/sequencer/micro_hbs_horizontal_program_store.sv rtl/sequencer/micro_hbs_horizontal_sequencer.sv tb/unit/tb_micro_hbs_horizontal_sequencer.sv
	vvp build/iverilog/horizontal_sequencer.vvp

rtl-horizontal-token-sequencer-test:
	mkdir -p build/iverilog
	$(PYTHON) scripts/compile_slh_dsa_horizontal_contexts.py > build/horizontal_context_compile.log
	iverilog -g2012 -Wall -s tb_micro_hbs_horizontal_token_sequencer -o build/iverilog/horizontal_token_sequencer.vvp rtl/sequencer/micro_hbs_event_scoreboard.sv rtl/sequencer/micro_hbs_horizontal_token_store.sv rtl/sequencer/micro_hbs_horizontal_template_store.sv rtl/sequencer/micro_hbs_horizontal_token_sequencer.sv tb/unit/tb_micro_hbs_horizontal_token_sequencer.sv
	vvp build/iverilog/horizontal_token_sequencer.vvp
	iverilog -g2012 -Wall -s tb_micro_hbs_horizontal_token_loop -o build/iverilog/horizontal_token_loop.vvp rtl/sequencer/micro_hbs_event_scoreboard.sv rtl/sequencer/micro_hbs_horizontal_token_store.sv rtl/sequencer/micro_hbs_horizontal_template_store.sv rtl/sequencer/micro_hbs_horizontal_token_sequencer.sv tb/unit/tb_micro_hbs_horizontal_token_loop.sv
	vvp build/iverilog/horizontal_token_loop.vvp
	iverilog -g2012 -Wall -s tb_micro_hbs_horizontal_token_image -o build/iverilog/horizontal_token_image.vvp rtl/sequencer/micro_hbs_event_scoreboard.sv rtl/sequencer/micro_hbs_horizontal_token_store.sv rtl/sequencer/micro_hbs_horizontal_template_store.sv rtl/sequencer/micro_hbs_horizontal_token_sequencer.sv tb/unit/tb_micro_hbs_horizontal_token_image.sv
	vvp build/iverilog/horizontal_token_image.vvp

rtl-horizontal-hash-lanes-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_hash_lane_service -o build/iverilog/horizontal_hash_lanes.vvp rtl/hash_lane/micro_hbs_keccak_f1600.sv rtl/hash_lane/micro_hbs_shake256_stream.sv rtl/hash_lane/micro_hbs_hash_lane_service.sv tb/unit/tb_micro_hbs_hash_lane_service.sv
	vvp build/iverilog/horizontal_hash_lanes.vvp

rtl-horizontal-keccak-lanes-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_horizontal_keccak_lane -o build/iverilog/horizontal_keccak_lanes.vvp rtl/hash_lane/micro_hbs_keccak_f1600.sv rtl/hash_lane/micro_hbs_horizontal_keccak_lane.sv tb/unit/tb_micro_hbs_horizontal_keccak_lane.sv
	vvp build/iverilog/horizontal_keccak_lanes.vvp

rtl-horizontal-shake-context-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_horizontal_shake_context_lane -o build/iverilog/horizontal_shake_context.vvp rtl/hash_lane/micro_hbs_keccak_f1600.sv rtl/hash_lane/micro_hbs_horizontal_shake_context_lane.sv tb/unit/tb_micro_hbs_horizontal_shake_context_lane.sv
	vvp build/iverilog/horizontal_shake_context.vvp

rtl-compact-shake-context-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_compact_shake_context_lane \
		-o build/iverilog/compact_shake_context.vvp \
		rtl/hash_lane/micro_hbs_keccak_round_explicit.sv \
		rtl/hash_lane/micro_hbs_compact_shake_context_lane.sv \
		tb/unit/tb_micro_hbs_compact_shake_context_lane.sv
	vvp build/iverilog/compact_shake_context.vvp

rtl-horizontal-slh-dsa-sign-test:
	$(VERILATOR) --binary --timing -Wno-fatal -Wno-WIDTH -Wno-LITENDIAN -O3 \
		--top-module tb_micro_hbs_horizontal_slh_dsa_sign_top \
		--Mdir build/verilator_horizontal_sign -o ../horizontal_sign_sim \
		-j $(VERILATOR_JOBS) rtl/hash_lane/micro_hbs_keccak_round_explicit.sv \
		rtl/hash_lane/micro_hbs_compact_shake_context_lane.sv \
		rtl/memory/micro_hbs_local_value_memories.sv \
		rtl/top/micro_hbs_horizontal_slh_dsa_sign_top.sv \
		tb/integration/tb_micro_hbs_horizontal_slh_dsa_sign_top.sv
	build/horizontal_sign_sim

rtl-state-manager-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_state_manager -o build/iverilog/state_manager.vvp rtl/state_manager/micro_hbs_state_manager.sv tb/unit/tb_micro_hbs_state_manager.sv
	vvp build/iverilog/state_manager.vvp

rtl-scratchpad-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_scratchpad64 -o build/iverilog/scratchpad64.vvp rtl/memory/micro_hbs_scratchpad64.sv tb/unit/tb_micro_hbs_scratchpad64.sv
	vvp build/iverilog/scratchpad64.vvp

rtl-affine-agu-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_affine_agu -o build/iverilog/affine_agu.vvp rtl/agu/micro_hbs_affine_agu.sv tb/unit/tb_micro_hbs_affine_agu.sv
	vvp build/iverilog/affine_agu.vvp

rtl-address-binding-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_address_binding_store -o build/iverilog/address_binding_store.vvp rtl/memory/micro_hbs_address_binding_store.sv tb/unit/tb_micro_hbs_address_binding_store.sv
	vvp build/iverilog/address_binding_store.vvp

rtl-scratch-load-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_scratch_load -o build/iverilog/scratch_load.vvp rtl/memory/micro_hbs_scratchpad64.sv rtl/memory/micro_hbs_scratch_load.sv tb/unit/tb_micro_hbs_scratch_load.sv
	vvp build/iverilog/scratch_load.vvp

rtl-data-descriptor-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_data_descriptor_store -o build/iverilog/data_descriptor_store.vvp rtl/memory/micro_hbs_data_descriptor_store.sv tb/unit/tb_micro_hbs_data_descriptor_store.sv
	vvp build/iverilog/data_descriptor_store.vvp

rtl-lms-tree-parent-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_lms_tree_parent -o build/iverilog/lms_tree_parent.vvp rtl/hash_lane/micro_hbs_sha256_bounded.sv rtl/treehash/micro_hbs_lms_tree_parent.sv tb/unit/tb_micro_hbs_lms_tree_parent.sv
	vvp build/iverilog/lms_tree_parent.vvp

rtl-xmss-tree-parent-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_xmss_tree_parent -o build/iverilog/xmss_tree_parent.vvp rtl/hash_lane/micro_hbs_keccak_f1600.sv rtl/hash_lane/micro_hbs_shake256_single_block.sv rtl/composer/micro_hbs_randomized_hash.sv rtl/treehash/micro_hbs_xmss_tree_parent.sv tb/unit/tb_micro_hbs_xmss_tree_parent.sv
	vvp build/iverilog/xmss_tree_parent.vvp

rtl-slh-dsa-tree-parent-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_slh_dsa_tree_parent -o build/iverilog/slh_dsa_tree_parent.vvp rtl/hash_lane/micro_hbs_keccak_f1600.sv rtl/hash_lane/micro_hbs_shake256_single_block.sv rtl/treehash/micro_hbs_slh_dsa_tree_parent.sv tb/unit/tb_micro_hbs_slh_dsa_tree_parent.sv
	vvp build/iverilog/slh_dsa_tree_parent.vvp

rtl-slh-dsa-job-stream-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_slh_dsa_job_stream_loader -o build/iverilog/slh_dsa_job_stream_loader.vvp rtl/memory/micro_hbs_scratchpad64.sv rtl/top/micro_hbs_slh_dsa_job_stream_loader.sv tb/integration/tb_micro_hbs_slh_dsa_job_stream_loader.sv
	vvp build/iverilog/slh_dsa_job_stream_loader.vvp

rtl-dynamic-loop-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_dynamic_loop -o build/iverilog/dynamic_loop.vvp rtl/sequencer/micro_hbs_program_store.sv rtl/sequencer/micro_hbs_sequencer.sv tb/unit/tb_micro_hbs_dynamic_loop.sv
	vvp build/iverilog/dynamic_loop.vvp

rtl-data-ops-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_data_ops -o build/iverilog/data_ops.vvp rtl/sequencer/micro_hbs_program_store.sv rtl/sequencer/micro_hbs_sequencer.sv tb/unit/tb_micro_hbs_data_ops.sv
	vvp build/iverilog/data_ops.vvp

rtl-output-stream-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_output_stream -o build/iverilog/output_stream.vvp rtl/output/micro_hbs_output_stream.sv tb/unit/tb_micro_hbs_output_stream.sv
	vvp build/iverilog/output_stream.vvp

rtl-output-stream-cycle-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_output_stream_cycles -o build/iverilog/output_stream_cycles.vvp rtl/output/micro_hbs_output_stream.sv tb/unit/tb_micro_hbs_output_stream_cycles.sv
	vvp build/iverilog/output_stream_cycles.vvp

rtl-scratch-alu-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_scratch_alu -o build/iverilog/scratch_alu.vvp rtl/memory/micro_hbs_scratchpad64.sv rtl/memory/micro_hbs_scratch_alu.sv tb/unit/tb_micro_hbs_scratch_alu.sv
	vvp build/iverilog/scratch_alu.vvp

rtl-base-w-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_base_w_checksum -o build/iverilog/base_w_checksum.vvp rtl/composer/micro_hbs_base_w_checksum.sv tb/unit/tb_micro_hbs_base_w_checksum.sv
	vvp build/iverilog/base_w_checksum.vvp

rtl-scratch-bitfield-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_scratch_bitfield_load -o build/iverilog/scratch_bitfield_load.vvp rtl/memory/micro_hbs_scratchpad64.sv rtl/memory/micro_hbs_scratch_bitfield_load.sv tb/unit/tb_micro_hbs_scratch_bitfield_load.sv
	vvp build/iverilog/scratch_bitfield_load.vvp

rtl-randomized-hash-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_randomized_hash -o build/iverilog/randomized_hash.vvp rtl/hash_lane/micro_hbs_keccak_f1600.sv rtl/hash_lane/micro_hbs_shake256_single_block.sv rtl/composer/micro_hbs_randomized_hash.sv tb/unit/tb_micro_hbs_randomized_hash.sv
	vvp build/iverilog/randomized_hash.vvp

rtl-layout-expr-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_layout_expr -o build/iverilog/layout_expr.vvp rtl/composer/micro_hbs_layout_expr.sv rtl/composer/micro_hbs_ordered_pair.sv tb/unit/tb_micro_hbs_layout_expr.sv
	vvp build/iverilog/layout_expr.vvp

rtl-layout-descriptor-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_layout_descriptor_store -o build/iverilog/layout_descriptor_store.vvp rtl/composer/micro_hbs_layout_descriptor_store.sv tb/unit/tb_micro_hbs_layout_descriptor_store.sv
	vvp build/iverilog/layout_descriptor_store.vvp

rtl-rate-append-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_rate_append64 -o build/iverilog/rate_append64.vvp rtl/composer/micro_hbs_rate_append64.sv tb/unit/tb_micro_hbs_rate_append64.sv
	vvp build/iverilog/rate_append64.vvp

rtl-rate-append128-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_rate_append128 -o build/iverilog/rate_append128.vvp rtl/composer/micro_hbs_rate_append128.sv tb/unit/tb_micro_hbs_rate_append128.sv
	vvp build/iverilog/rate_append128.vvp

rtl-banked-scratchpad-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_scratchpad64_banked -o build/iverilog/scratchpad64_banked.vvp rtl/memory/micro_hbs_scratchpad64.sv rtl/memory/micro_hbs_scratchpad64_banked.sv tb/unit/tb_micro_hbs_scratchpad64_banked.sv
	vvp build/iverilog/scratchpad64_banked.vvp

rtl-feedback-cache-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_hash_feedback_cache -o build/iverilog/hash_feedback_cache.vvp rtl/composer/micro_hbs_hash_feedback_cache.sv tb/unit/tb_micro_hbs_hash_feedback_cache.sv
	vvp build/iverilog/hash_feedback_cache.vvp

rtl-treehash-dynamic-test:
	mkdir -p build/iverilog
	iverilog -g2012 -Wall -s tb_micro_hbs_treehash_min_dynamic -o build/iverilog/treehash_min_dynamic.vvp rtl/treehash/micro_hbs_treehash_min_dynamic.sv tb/unit/tb_micro_hbs_treehash_min_dynamic.sv
	vvp build/iverilog/treehash_min_dynamic.vvp

rtl-unit-test: rtl-keccak-test rtl-sha256-bounded-test rtl-shake-test \
	rtl-shake-stream-test rtl-shake-stream-cycle-test rtl-state-manager-test \
	rtl-scratchpad-test rtl-affine-agu-test rtl-address-binding-test \
	rtl-scratch-load-test rtl-data-descriptor-test rtl-lms-tree-parent-test \
	rtl-xmss-tree-parent-test rtl-slh-dsa-tree-parent-test \
	rtl-slh-dsa-job-stream-test rtl-dynamic-loop-test rtl-data-ops-test \
	rtl-output-stream-test rtl-output-stream-cycle-test rtl-scratch-alu-test \
	rtl-base-w-test rtl-scratch-bitfield-test rtl-randomized-hash-test \
	rtl-layout-expr-test rtl-layout-descriptor-test rtl-rate-append-test \
	rtl-rate-append128-test rtl-banked-scratchpad-test \
	rtl-treehash-dynamic-test rtl-feedback-cache-test

rtl-slh-dsa-full-test:
	mkdir -p build/verilator/slh_dsa_full
	+$(VERILATOR) --binary --timing -O3 -j $(VERILATOR_JOBS) -Wno-fatal -Wno-TIMESCALEMOD \
		-Wno-WIDTH -Wno-CMPCONST --top-module tb_micro_hbs_slh_dsa_top \
		--Mdir build/verilator/slh_dsa_full -o slh_dsa_full_tb \
		$(SLH_DSA_RTL) tb/integration/tb_micro_hbs_slh_dsa_top.sv
	build/verilator/slh_dsa_full/slh_dsa_full_tb

# Parameter sweep entry point.  Functional/counter checks remain enabled for
# every U; the historical exact-cycle assertions apply only to U=2.
rtl-slh-dsa-full-profile:
	mkdir -p build/verilator/slh_dsa_full_u$(SLH_DSA_UNROLL)
	+$(VERILATOR) --binary --timing -O3 -j $(VERILATOR_JOBS) -Wno-fatal -Wno-TIMESCALEMOD \
		-Wno-WIDTH -Wno-CMPCONST --top-module tb_micro_hbs_slh_dsa_top \
		-GDUT_UNROLL=$(SLH_DSA_UNROLL) \
		--Mdir build/verilator/slh_dsa_full_u$(SLH_DSA_UNROLL) \
		-o slh_dsa_full_u$(SLH_DSA_UNROLL)_tb \
		$(SLH_DSA_RTL) tb/integration/tb_micro_hbs_slh_dsa_top.sv
	build/verilator/slh_dsa_full_u$(SLH_DSA_UNROLL)/slh_dsa_full_u$(SLH_DSA_UNROLL)_tb

rtl-slh-dsa-static-test:
	mkdir -p build/verilator/slh_dsa_static
	+$(VERILATOR) --binary --timing -O3 -j $(VERILATOR_JOBS) -Wno-fatal -Wno-TIMESCALEMOD \
		-Wno-WIDTH -Wno-CMPCONST --top-module tb_micro_hbs_slh_dsa_static_top \
		--Mdir build/verilator/slh_dsa_static -o slh_dsa_static_tb \
		$(SLH_DSA_RTL) tb/integration/tb_micro_hbs_slh_dsa_static_top.sv
	build/verilator/slh_dsa_static/slh_dsa_static_tb

rtl-test: rtl-unit-test rtl-slh-dsa-full-test

export-rtl-microcode:
	$(PYTHON) scripts/export_rtl_microcode.py

export-xmss-layouts:
	$(PYTHON) scripts/export_xmss_layouts.py

export-slh-dsa-layouts:
	$(PYTHON) scripts/export_slh_dsa_layouts.py

synth-keccak-u1:
	mkdir -p build/vivado/keccak_u1
	vivado -mode batch -nolog -nojournal -log build/vivado/keccak_u1/vivado.log -source experiments/synth_keccak_lane.tcl -tclargs 1

synth-keccak-u2:
	mkdir -p build/vivado/keccak_u2
	vivado -mode batch -nolog -nojournal -log build/vivado/keccak_u2/vivado.log -source experiments/synth_keccak_lane.tcl -tclargs 2

collect-keccak-ppa:
	$(PYTHON) experiments/collect_keccak_ppa.py

synth-layout-expr32:
	mkdir -p build/vivado/layout_expr32
	vivado -mode batch -nolog -nojournal -log build/vivado/layout_expr32/vivado.log -source experiments/synth_layout_expr32.tcl

collect-layout-expr32-ppa:
	$(PYTHON) experiments/collect_layout_expr32_ppa.py

synth-scratchpad-full:
	mkdir -p build/vivado/scratchpad_full
	vivado -mode batch -nolog -nojournal -log build/vivado/scratchpad_full/vivado.log -source experiments/synth_scratchpad.tcl -tclargs 8192 full

synth-scratchpad-min:
	mkdir -p build/vivado/scratchpad_min
	vivado -mode batch -nolog -nojournal -log build/vivado/scratchpad_min/vivado.log -source experiments/synth_scratchpad.tcl -tclargs 84 min

collect-scratchpad-ppa:
	$(PYTHON) experiments/collect_scratchpad_ppa.py

synth-slh-dsa-full:
	mkdir -p build/vivado/$(VIVADO_TAG)
	vivado -mode batch -nolog -nojournal -log build/vivado/$(VIVADO_TAG)/vivado.log -source experiments/synth_slh_dsa_top.tcl -tclargs $(VIVADO_TAG)

synth-slh-dsa-static-full:
	mkdir -p build/vivado/$(VIVADO_TAG)
	vivado -mode batch -nolog -nojournal -log build/vivado/$(VIVADO_TAG)/vivado.log -source experiments/synth_slh_dsa_static_top.tcl -tclargs $(VIVADO_TAG)

synth-horizontal-hash-core:
	mkdir -p build/vivado/horizontal_hash_core
	vivado -mode batch -nolog -nojournal -log build/vivado/horizontal_hash_core/vivado.log -source experiments/synth_horizontal_hash_core.tcl

synth-horizontal-token-hash-core:
	mkdir -p build/vivado/horizontal_token_hash_core
	vivado -mode batch -nolog -nojournal -log build/vivado/horizontal_token_hash_core/vivado.log -source experiments/synth_horizontal_token_hash_core.tcl

synth-horizontal-slh-dsa-sign:
	mkdir -p build/vivado/$(HORIZONTAL_SIGN_TAG)
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/$(HORIZONTAL_SIGN_TAG)_driver.log \
		-source experiments/synth_horizontal_slh_dsa_sign_top.tcl \
		-tclargs $(HORIZONTAL_SIGN_TAG) $(HORIZONTAL_SIGN_PART)

post-route-horizontal-slh-dsa-sign:
	mkdir -p build/vivado/$(HORIZONTAL_SIGN_POSTROUTE_TAG)
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/$(HORIZONTAL_SIGN_POSTROUTE_TAG)_driver.log \
		-source experiments/post_route_horizontal_slh_dsa_sign.tcl \
		-tclargs $(HORIZONTAL_SIGN_TAG) $(HORIZONTAL_SIGN_POSTROUTE_TAG)

compare-unified-hbs-paper:
	$(PYTHON) experiments/audit_workload.py
	$(PYTHON) experiments/project_xmss_cache_sign.py

check-standalone:
	$(PYTHON) scripts/check_standalone.py

check-parallel-isolation:
	$(PYTHON) scripts/check_parallel_isolation.py

ci-core: lint test sim-lms sim-xmss sim-slh-dsa sim-slh-dsa-cycles rtl-test

ci: ci-core check-standalone

reproduce: ci compare-unified-hbs-paper

artifact:
	@echo 'artifact: NOT IMPLEMENTED (Gate 8 is open)'; exit 2
