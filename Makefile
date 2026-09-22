PYTHON ?= python3
VERILATOR ?= verilator
JOBS ?= 8
VERILATOR_JOBS ?= $(JOBS)
SWAP ?= 0
BACKPRESSURE ?= 0
UNROLL ?= 2
# An explicit LANES overrides all products; otherwise use the screened topology.
SLH_LANES ?= $(if $(LANES),$(LANES),2)
XMSS_LANES ?= $(if $(LANES),$(LANES),1)
LMS_LANES ?= $(if $(LANES),$(LANES),1)

PART ?= xc7a200tffg1156-3
SLH_DSA_TAG ?= uhbs_slh_dsa
XMSS_TAG ?= uhbs_xmss
LMS_TAG ?= uhbs_lms

UHBS_RTL := $(shell cat manifests/unified_sources.txt)

.PHONY: all test test-unified lint compile-microcode generate-vectors \
	rtl-unit-test rtl-slh-dsa-test rtl-xmss-test rtl-lms-test rtl-test \
	synth-slh-dsa synth-xmss synth-lms reproduce-paper-comparison

all: rtl-test

test: test-unified

test-unified:
	$(PYTHON) -m unittest tests.test_unified_hbs tests.test_unified_rtl_contract -v

lint:
	$(PYTHON) -m compileall -q model scripts experiments tests
	$(VERILATOR) --lint-only --timing -Wno-fatal -Wno-WIDTH \
		-Wno-LITENDIAN --top-module uhbs_slh_dsa_top $(UHBS_RTL)
	$(VERILATOR) --lint-only --timing -Wno-fatal -Wno-WIDTH \
		-Wno-LITENDIAN -Wno-PINCONNECTEMPTY -Wno-UNOPTFLAT \
		--top-module uhbs_xmss_top $(UHBS_RTL)

compile-microcode:
	$(PYTHON) -m unittest tests.test_unified_hbs -v
	$(PYTHON) scripts/compile_unified_hbs.py
	$(PYTHON) scripts/generate_unified_tops.py

generate-vectors: compile-microcode

rtl-unit-test:
	mkdir -p build/iverilog
	$(PYTHON) scripts/generate_unified_lane_vectors.py
	iverilog -g2012 -s tb_uhbs_word_output_packer -o build/iverilog/unified_packer.vvp \
		rtl/output/uhbs_word_output_packer.sv tb/unit/tb_uhbs_word_output_packer.sv
	vvp build/iverilog/unified_packer.vvp
	iverilog -g2012 -s tb_uhbs_admission -o build/iverilog/unified_admission.vvp \
		$(UHBS_RTL) tb/unit/tb_uhbs_admission.sv
	vvp build/iverilog/unified_admission.vvp
	@for profile in 0 1 2; do \
		iverilog -g2012 -s tb_uhbs_recipe_lane -Ptb_uhbs_recipe_lane.PROFILE=$$profile \
		-o build/iverilog/unified_recipe_$$profile.vvp rtl/hash_lane/uhbs_keccak.sv \
		rtl/hash_lane/uhbs_compact_shake_context_lane.sv rtl/hash_lane/uhbs_recipe_lane.sv \
		tb/unit/tb_uhbs_recipe_lane.sv && vvp build/iverilog/unified_recipe_$$profile.vvp || exit 1; \
	done
	iverilog -g2012 -o build/iverilog/uhbs_stateful_index_guard.vvp \
		rtl/control/uhbs_stateful_index_guard.sv \
		tb/unit/tb_uhbs_stateful_index_guard.sv
	vvp build/iverilog/uhbs_stateful_index_guard.vvp
	iverilog -g2012 -o build/iverilog/uhbs_compact_shake_context_lane.vvp \
		rtl/hash_lane/uhbs_keccak.sv \
		rtl/hash_lane/uhbs_compact_shake_context_lane.sv \
		tb/unit/tb_uhbs_compact_shake_context_lane.sv
	vvp build/iverilog/uhbs_compact_shake_context_lane.vvp

rtl-slh-dsa-test:
	+$(VERILATOR) --binary --timing -O3 -j $(VERILATOR_JOBS) \
		-Wno-fatal -Wno-WIDTH -Wno-LITENDIAN --top-module tb_uhbs_unified \
		-GPROFILE=0 -GSWAP=$(SWAP) -GBACKPRESSURE=$(BACKPRESSURE) -GLANES=$(SLH_LANES) -GUNROLL=$(UNROLL) \
		--Mdir build/verilator-unified-slh $(UHBS_RTL) tb/integration/tb_uhbs_unified.sv
	build/verilator-unified-slh/Vtb_uhbs_unified

rtl-xmss-test:
	+$(VERILATOR) --binary --timing -O3 -j $(VERILATOR_JOBS) \
		-Wno-fatal -Wno-WIDTH -Wno-LITENDIAN -Wno-PINCONNECTEMPTY \
		-Wno-UNOPTFLAT --top-module tb_uhbs_unified \
		-GPROFILE=1 -GSWAP=$(SWAP) -GBACKPRESSURE=$(BACKPRESSURE) -GLANES=$(XMSS_LANES) -GUNROLL=$(UNROLL) --Mdir build/verilator-unified-xmss \
		$(UHBS_RTL) tb/integration/tb_uhbs_unified.sv
	build/verilator-unified-xmss/Vtb_uhbs_unified

rtl-lms-test:
	+$(VERILATOR) --binary --timing -O3 -j $(VERILATOR_JOBS) \
		-Wno-fatal -Wno-WIDTH -Wno-LITENDIAN -Wno-PINCONNECTEMPTY \
		-Wno-UNOPTFLAT --top-module tb_uhbs_unified \
		-GPROFILE=2 -GSWAP=$(SWAP) -GBACKPRESSURE=$(BACKPRESSURE) -GLANES=$(LMS_LANES) -GUNROLL=$(UNROLL) --Mdir build/verilator-unified-lms \
		$(UHBS_RTL) tb/integration/tb_uhbs_unified.sv
	build/verilator-unified-lms/Vtb_uhbs_unified

rtl-test: rtl-unit-test rtl-slh-dsa-test rtl-xmss-test rtl-lms-test

synth-slh-dsa:
	mkdir -p build/vivado/$(SLH_DSA_TAG)
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/$(SLH_DSA_TAG)_driver.log \
		-source experiments/synth_unified_hbs.tcl \
		-tclargs slh $(SLH_DSA_TAG) $(UNROLL) $(SLH_LANES)

synth-xmss:
	mkdir -p build/vivado/$(XMSS_TAG)
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/$(XMSS_TAG)_driver.log \
		-source experiments/synth_unified_hbs.tcl \
		-tclargs xmss $(XMSS_TAG) $(UNROLL) $(XMSS_LANES)

synth-lms:
	mkdir -p build/vivado/$(LMS_TAG)
	vivado -mode batch -nolog -nojournal \
		-log build/vivado/$(LMS_TAG)_driver.log \
		-source experiments/synth_unified_hbs.tcl \
		-tclargs lms $(LMS_TAG) $(UNROLL) $(LMS_LANES)

reproduce-paper-comparison:
	$(PYTHON) scripts/reproduce_paper_comparison.py
