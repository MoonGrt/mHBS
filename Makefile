PYTHON ?= python3
VERILATOR ?= verilator
JOBS ?= 8
VERILATOR_JOBS ?= $(JOBS)

PART ?= xc7a200tffg1156-3
SLH_DSA_TAG ?= uhbs_slh_dsa
XMSS_TAG ?= uhbs_xmss
LMS_TAG ?= uhbs_lms

STATELESS_RTL := \
	rtl/sequencer/uhbs_event_scoreboard.sv \
	rtl/sequencer/uhbs_static_task_sequencer.sv \
	rtl/hash_lane/uhbs_keccak.sv \
	rtl/hash_lane/uhbs_compact_shake_context_lane.sv \
	rtl/memory/uhbs_local_value_memories.sv \
	rtl/top/uhbs_stateless_hbs.sv \
	rtl/top/uhbs_slh_dsa_top.sv

STATEFUL_RTL := \
	rtl/sequencer/uhbs_event_scoreboard.sv \
	rtl/sequencer/uhbs_static_task_sequencer.sv \
	rtl/hash_lane/uhbs_keccak.sv \
	rtl/hash_lane/uhbs_compact_shake_context_lane.sv \
	rtl/hash_lane/uhbs_stateful_recipe_lane.sv \
	rtl/control/uhbs_stateful_index_guard.sv \
	rtl/memory/uhbs_endpoint_scratch256.sv \
	rtl/memory/uhbs_full_tree_cache256.sv \
	rtl/treehash/uhbs_tree_push_reducer.sv \
	rtl/output/uhbs_byte_output_packer.sv \
	rtl/top/uhbs_stateful_hbs.sv \
	rtl/top/uhbs_xmss_top.sv \
	rtl/top/uhbs_lms_top.sv

.PHONY: all test lint compile-microcode generate-vectors \
	rtl-unit-test rtl-slh-dsa-test rtl-xmss-test rtl-lms-test rtl-test \
	synth-keccak synth-lane synth-slh-dsa synth-xmss synth-lms

all: rtl-test

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

lint:
	$(PYTHON) -m compileall -q model scripts experiments tests
	$(VERILATOR) --lint-only --timing -Wno-fatal -Wno-WIDTH \
		-Wno-LITENDIAN --top-module uhbs_slh_dsa_sign_top $(STATELESS_RTL)
	$(VERILATOR) --lint-only --timing -Wno-fatal -Wno-WIDTH \
		-Wno-LITENDIAN -Wno-PINCONNECTEMPTY -Wno-UNOPTFLAT \
		--top-module uhbs_xmss_top $(STATEFUL_RTL)

compile-microcode:
	$(PYTHON) scripts/compile_generic_hbs_macrocode.py
	$(PYTHON) scripts/compile_stateful_hbs_macrocode.py

generate-vectors: compile-microcode
	$(PYTHON) scripts/generate_stateful_rtl_vectors.py

rtl-unit-test:
	mkdir -p build/iverilog
	iverilog -g2012 -o build/iverilog/uhbs_tree_push_reducer.vvp \
		rtl/treehash/uhbs_tree_push_reducer.sv \
		tb/unit/tb_uhbs_tree_push_reducer.sv
	vvp build/iverilog/uhbs_tree_push_reducer.vvp
	iverilog -g2012 -o build/iverilog/uhbs_full_tree_cache256.vvp \
		rtl/memory/uhbs_full_tree_cache256.sv \
		tb/unit/tb_uhbs_full_tree_cache256.sv
	vvp build/iverilog/uhbs_full_tree_cache256.vvp
	iverilog -g2012 -o build/iverilog/uhbs_stateful_index_guard.vvp \
		rtl/control/uhbs_stateful_index_guard.sv \
		tb/unit/tb_uhbs_stateful_index_guard.sv
	vvp build/iverilog/uhbs_stateful_index_guard.vvp
	iverilog -g2012 -o build/iverilog/uhbs_stateful_recipe_lane.vvp \
		rtl/hash_lane/uhbs_keccak.sv \
		rtl/hash_lane/uhbs_compact_shake_context_lane.sv \
		rtl/hash_lane/uhbs_stateful_recipe_lane.sv \
		tb/unit/tb_uhbs_stateful_recipe_lane.sv
	vvp build/iverilog/uhbs_stateful_recipe_lane.vvp
	iverilog -g2012 -o build/iverilog/uhbs_byte_output_packer.vvp \
		rtl/output/uhbs_byte_output_packer.sv \
		tb/unit/tb_uhbs_byte_output_packer.sv
	vvp build/iverilog/uhbs_byte_output_packer.vvp
	iverilog -g2012 -o build/iverilog/uhbs_compact_shake_context_lane.vvp \
		rtl/hash_lane/uhbs_keccak.sv \
		rtl/hash_lane/uhbs_compact_shake_context_lane.sv \
		tb/unit/tb_uhbs_compact_shake_context_lane.sv
	vvp build/iverilog/uhbs_compact_shake_context_lane.vvp

rtl-slh-dsa-test: compile-microcode
	+$(VERILATOR) --binary --timing -O3 -j $(VERILATOR_JOBS) \
		-Wno-fatal -Wno-WIDTH -Wno-LITENDIAN \
		--top-module tb_uhbs_slh_dsa_keygen_top \
		--Mdir build/verilator-uhbs-slh-keygen \
		$(STATELESS_RTL) tb/integration/tb_uhbs_slh_dsa_keygen_top.sv
	build/verilator-uhbs-slh-keygen/Vtb_uhbs_slh_dsa_keygen_top
	+$(VERILATOR) --binary --timing -O3 -j $(VERILATOR_JOBS) \
		-Wno-fatal -Wno-WIDTH -Wno-LITENDIAN \
		--top-module tb_uhbs_slh_dsa_sign_top \
		--Mdir build/verilator-uhbs-slh-sign \
		$(STATELESS_RTL) tb/integration/tb_uhbs_slh_dsa_sign_top.sv
	build/verilator-uhbs-slh-sign/Vtb_uhbs_slh_dsa_sign_top

rtl-xmss-test: generate-vectors
	+$(VERILATOR) --binary --timing -O3 -j $(VERILATOR_JOBS) \
		-Wno-fatal -Wno-WIDTH -Wno-LITENDIAN -Wno-PINCONNECTEMPTY \
		-Wno-UNOPTFLAT --top-module tb_uhbs_stateful_products \
		-GPROFILE=0 --Mdir build/verilator-uhbs-xmss \
		$(STATEFUL_RTL) tb/integration/tb_uhbs_stateful_products.sv
	build/verilator-uhbs-xmss/Vtb_uhbs_stateful_products

rtl-lms-test: generate-vectors
	+$(VERILATOR) --binary --timing -O3 -j $(VERILATOR_JOBS) \
		-Wno-fatal -Wno-WIDTH -Wno-LITENDIAN -Wno-PINCONNECTEMPTY \
		-Wno-UNOPTFLAT --top-module tb_uhbs_stateful_products \
		-GPROFILE=1 --Mdir build/verilator-uhbs-lms \
		$(STATEFUL_RTL) tb/integration/tb_uhbs_stateful_products.sv
	build/verilator-uhbs-lms/Vtb_uhbs_stateful_products

rtl-test: rtl-unit-test rtl-slh-dsa-test rtl-xmss-test rtl-lms-test

synth-keccak:
	mkdir -p build/vivado/uhbs_keccak
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/uhbs_keccak_driver.log \
		-source experiments/synth_keccak_round.tcl

synth-lane:
	mkdir -p build/vivado/uhbs_compact_lane
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/uhbs_compact_lane_driver.log \
		-source experiments/synth_compact_lane.tcl

synth-slh-dsa:
	mkdir -p build/vivado/$(SLH_DSA_TAG)
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/$(SLH_DSA_TAG)_driver.log \
		-source experiments/synth_horizontal_slh_dsa_sign_top.tcl \
		-tclargs $(SLH_DSA_TAG) $(PART)

synth-xmss:
	mkdir -p build/vivado/$(XMSS_TAG)
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/$(XMSS_TAG)_driver.log \
		-source experiments/synth_stateful_hbs_top.tcl \
		-tclargs xmss $(XMSS_TAG) $(PART)

synth-lms:
	mkdir -p build/vivado/$(LMS_TAG)
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/$(LMS_TAG)_driver.log \
		-source experiments/synth_stateful_hbs_top.tcl \
		-tclargs lms $(LMS_TAG) $(PART)
