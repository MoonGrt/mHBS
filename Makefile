SHELL := /bin/bash
PYTHON ?= python3
VERILATOR ?= verilator
JOBS ?= 8
PROFILE ?= all
LANES ?= 2
UNROLL ?= 2
SWAP ?= 0
SYNTH_DIRECTIVE ?= Default
FLATTEN ?= rebuilt
TAG ?= slh_only_l$(LANES)_c0
UHBS_RTL := $(shell cat manifests/unified_sources.txt)

.PHONY: all test area-software-test compile-microcode lint rtl-profile-test rtl-all-profiles rtl-test rtl-unit-test synth-common route-common freeze-common reproduce-paper-comparison reproduce-slh-only
all: rtl-test
test: area-software-test
area-software-test:
	$(PYTHON) scripts/verify_slh_only_models.py
compile-microcode:
	$(PYTHON) scripts/compile_slh_only.py
lint:
	$(VERILATOR) --lint-only --timing -Wno-fatal -Wno-WIDTH -Wno-UNOPTFLAT --top-module uhbs_top $(UHBS_RTL)
rtl-profile-test:
	$(PYTHON) scripts/autonomous_flow.py sim --profile $(PROFILE) --lanes $(LANES) --unroll $(UNROLL) --swap $(SWAP) --jobs $(JOBS)
rtl-all-profiles:
	$(MAKE) rtl-profile-test PROFILE=all
architecture-test:
	$(PYTHON) scripts/verify_microcode_architecture.py
rtl-unit-test:
	$(PYTHON) scripts/verify_slh_only_units.py
rtl-test: rtl-unit-test rtl-all-profiles
rtl-verification: architecture-test
	$(PYTHON) scripts/autonomous_flow.py sim --boundaries --message-cases --lanes $(LANES) --unroll $(UNROLL) --jobs $(JOBS)
	$(PYTHON) scripts/autonomous_flow.py sim --boundaries --message-cases --replay --lanes $(LANES) --unroll $(UNROLL) --jobs $(JOBS)
	$(PYTHON) scripts/autonomous_flow.py sim --swap 1 --lanes $(LANES) --unroll $(UNROLL) --jobs $(JOBS)
	$(PYTHON) scripts/verify_slh_only_faults.py
synth-common:
	$(PYTHON) scripts/autonomous_flow.py capture --tag $(TAG) --lanes $(LANES) --unroll $(UNROLL)
	mkdir -p build/v4.1/$(TAG)
	vivado -mode batch -nolog -nojournal -source experiments/v4.1/synth.tcl -tclargs $(TAG) $(LANES) $(UNROLL) $(SYNTH_DIRECTIVE) $(FLATTEN) > build/v4.1/$(TAG)_synth.log 2>&1
	$(PYTHON) scripts/autonomous_flow.py collect --tag $(TAG)
route-common:
	$(PYTHON) scripts/autonomous_flow.py prepare_route --tag $(TAG)
	vivado -mode batch -nolog -nojournal -source experiments/v4.1/route.tcl -tclargs $(TAG)_route > build/v4.1/$(TAG)_route.log 2>&1
	$(PYTHON) scripts/autonomous_flow.py collect --tag $(TAG)_route --route
freeze-common:
	$(PYTHON) scripts/compile_slh_only.py
	vivado -mode batch -nolog -nojournal -source experiments/v4.1/freeze_slh_only.tcl -tclargs $(TAG)_route > build/v4.1/$(TAG)_freeze.log 2>&1
reproduce-paper-comparison:
	$(PYTHON) scripts/reproduce_paper_comparison.py
	$(PYTHON) scripts/reproduce_seven_profiles.py
	$(PYTHON) scripts/reproduce_autonomous.py --allow-incomplete
reproduce-slh-only:
	$(PYTHON) scripts/reproduce_slh_only.py
