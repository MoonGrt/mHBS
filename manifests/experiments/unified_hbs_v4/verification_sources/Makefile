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

SHELL := /bin/bash
PROFILES := slh_128f slh_192f slh_256f xmss_omega2 xmss_omega4 lms_omega2 lms_omega4
Q ?= 5
PROFILE ?= slh_128f
PROFILE_ID := $(shell $(PYTHON) -c 'from model.profiles import PROFILES; print(list(PROFILES).index("$(PROFILE)"))')
PROFILE_LANES = $(if $(LANES),$(LANES),$(if $(filter slh_%,$(PROFILE)),2,1))
TAG ?= v4d_$(PROFILE)_u$(UNROLL)_l$(PROFILE_LANES)
SIMULATION ?= $(TAG)_s0_b0
SIM_TAG = $(TAG)_s$(SWAP)_b$(BACKPRESSURE)$(if $(filter 5,$(Q)),,_q$(Q))
UHBS_RTL := $(shell cat manifests/unified_sources.txt)

.PHONY: all test test-unified lint compile-microcode generate-vectors rtl-unit-test rtl-test rtl-profile-test rtl-all-profiles synth-profile synth-all-profiles route-profile reproduce-paper-comparison
all: rtl-test

test: test-unified

test-unified:
	$(PYTHON) -m unittest tests.test_unified_hbs tests.test_seven_profiles tests.test_unified_rtl_contract -v

lint:
	@for profile in $(PROFILES); do $(VERILATOR) --lint-only --timing -Wno-fatal -Wno-WIDTH -Wno-LITENDIAN --top-module uhbs_$${profile}_top $(UHBS_RTL) || exit 1; done

compile-microcode:
	$(PYTHON) scripts/verify_seven_models.py
	$(PYTHON) scripts/compile_unified_hbs.py
	$(PYTHON) scripts/generate_boundary_vectors.py
	$(PYTHON) scripts/generate_unified_tops.py

generate-vectors: compile-microcode
	$(PYTHON) scripts/generate_unified_lane_vectors.py

rtl-unit-test:
	mkdir -p build/iverilog
	$(PYTHON) scripts/generate_unified_lane_vectors.py
	iverilog -g2012 -s tb_uhbs_value_store -o build/iverilog/value_store.vvp rtl/memory/uhbs_value_store.sv tb/unit/tb_uhbs_value_store.sv
	vvp build/iverilog/value_store.vvp
	iverilog -g2012 -s tb_uhbs_word_output_packer -o build/iverilog/unified_packer.vvp rtl/output/uhbs_word_output_packer.sv tb/unit/tb_uhbs_word_output_packer.sv
	vvp build/iverilog/unified_packer.vvp
	@for profile in 3 4 5 6; do \
		iverilog -g2012 -s tb_uhbs_admission -Ptb_uhbs_admission.PROFILE=$$profile -o build/iverilog/unified_admission_$$profile.vvp $(UHBS_RTL) tb/unit/tb_uhbs_admission.sv && vvp build/iverilog/unified_admission_$$profile.vvp || exit 1; \
	done
	@for profile in 0 1 2 3 4 5 6; do \
		iverilog -g2012 -s tb_uhbs_recipe_lane -Ptb_uhbs_recipe_lane.PROFILE=$$profile -o build/iverilog/unified_recipe_$$profile.vvp rtl/hash_lane/uhbs_keccak.sv rtl/hash_lane/uhbs_compact_shake_context_lane.sv rtl/hash_lane/uhbs_recipe_lane.sv tb/unit/tb_uhbs_recipe_lane.sv && vvp build/iverilog/unified_recipe_$$profile.vvp || exit 1; \
	done
	iverilog -g2012 -s tb_uhbs_stateful_index_guard -o build/iverilog/guard.vvp rtl/control/uhbs_stateful_index_guard.sv tb/unit/tb_uhbs_stateful_index_guard.sv
	vvp build/iverilog/guard.vvp
	iverilog -g2012 -s tb_uhbs_compact_shake_context_lane -o build/iverilog/compact.vvp rtl/hash_lane/uhbs_keccak.sv rtl/hash_lane/uhbs_compact_shake_context_lane.sv tb/unit/tb_uhbs_compact_shake_context_lane.sv
	vvp build/iverilog/compact.vvp

rtl-profile-test:
	+$(VERILATOR) --binary --timing -O3 -j $(VERILATOR_JOBS) -Wno-fatal -Wno-WIDTH -Wno-LITENDIAN -Wno-PINCONNECTEMPTY -Wno-UNOPTFLAT --top-module tb_uhbs_unified -GQ=$(Q) -GPROFILE=$(PROFILE_ID) -GSWAP=$(SWAP) -GBACKPRESSURE=$(BACKPRESSURE) -GLANES=$(PROFILE_LANES) -GUNROLL=$(UNROLL) --Mdir build/verilator-$(SIM_TAG) $(UHBS_RTL) tb/integration/tb_uhbs_unified.sv
	$(PYTHON) scripts/run_unified_sim.py $(SIM_TAG) $(PROFILE) $(UNROLL) $(PROFILE_LANES) build/verilator-$(SIM_TAG)/Vtb_uhbs_unified

rtl-all-profiles:
	@for profile in $(PROFILES); do $(MAKE) rtl-profile-test PROFILE=$$profile || exit 1; done
rtl-test: rtl-unit-test rtl-all-profiles

synth-profile:
	mkdir -p build/vivado/$(TAG)
	vivado -mode batch -nolog -nojournal -log build/vivado/$(TAG)_driver.log -source experiments/synth_unified_hbs.tcl -tclargs $(PROFILE) $(TAG) $(UNROLL) $(PROFILE_LANES)
	$(PYTHON) scripts/collect_unified_ppa.py $(TAG) $(PROFILE) --simulation $(SIMULATION) --period 10.0

synth-all-profiles:
	@for profile in $(PROFILES); do $(MAKE) synth-profile PROFILE=$$profile || exit 1; done

route-profile:
	vivado -mode batch -nolog -nojournal -log build/vivado/$(TAG)_route_driver.log -source experiments/route_unified_hbs.tcl -tclargs $(TAG) 10.0 $(TAG)_route
	vivado -mode batch -nolog -nojournal -log build/vivado/$(TAG)_clock_driver.log -source experiments/finalize_unified_clock.tcl -tclargs $(TAG)_route
	$(PYTHON) scripts/collect_unified_ppa.py $(TAG)_route $(PROFILE) --simulation $(SIMULATION) --route

rtl-slh-dsa-test:
	$(MAKE) rtl-profile-test PROFILE=slh_128f LANES=$(SLH_LANES)
rtl-xmss-test:
	$(MAKE) rtl-profile-test PROFILE=xmss_omega4 LANES=$(XMSS_LANES)
rtl-lms-test:
	$(MAKE) rtl-profile-test PROFILE=lms_omega4 LANES=$(LMS_LANES)
synth-slh-dsa:
	$(MAKE) synth-profile PROFILE=slh_128f LANES=$(SLH_LANES)
synth-xmss:
	$(MAKE) synth-profile PROFILE=xmss_omega4 LANES=$(XMSS_LANES)
synth-lms:
	$(MAKE) synth-profile PROFILE=lms_omega4 LANES=$(LMS_LANES)

reproduce-paper-comparison:
	$(PYTHON) scripts/reproduce_paper_comparison.py
	$(PYTHON) scripts/reproduce_seven_profiles.py

rtl-verification:
	$(PYTHON) scripts/verify_rtl_matrix.py

route-all-profiles:
	@for profile in $(PROFILES); do $(MAKE) route-profile PROFILE=$$profile || exit 1; done

archive-seven-profiles:
	$(PYTHON) scripts/archive_seven_profiles.py
	$(PYTHON) scripts/reproduce_seven_profiles.py --write-comparison
