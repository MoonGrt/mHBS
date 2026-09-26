SHELL := /bin/bash
PYTHON ?= python3
VERILATOR ?= verilator
PROFILE ?= all
OPERATION ?= all
SWAP ?= 0
TAG ?= compact_v42
SIM_TAG ?= $(TAG)
UHBS_RTL := $(shell cat manifests/v42_sources.txt)

.PHONY: all test compile-microcode lint rtl-unit-test rtl-profile-test rtl-all-profiles rtl-test rtl-verification synth-common route-common freeze-common report-v42 reproduce-v42
all: rtl-test
test: compile-microcode
compile-microcode:
	$(PYTHON) scripts/verify_v42_models.py
	$(PYTHON) scripts/verify_v42_format.py
lint:
	$(VERILATOR) --lint-only --timing -Wno-fatal -Wno-WIDTH -Wno-UNOPTFLAT --top-module uhbs_top $(UHBS_RTL)
rtl-unit-test:
	$(PYTHON) scripts/verify_v42_units.py
rtl-profile-test:
	$(PYTHON) scripts/v42_flow.py sim --tag $(TAG) --profile $(PROFILE) --operation $(OPERATION) --swap $(SWAP)
rtl-all-profiles:
	$(MAKE) rtl-profile-test PROFILE=all OPERATION=all
rtl-test: rtl-unit-test rtl-all-profiles
rtl-verification:
	$(PYTHON) scripts/verify_v42_snapshot.py $(TAG)
synth-common:
	$(PYTHON) scripts/v42_flow.py capture --tag $(TAG)
	$(PYTHON) scripts/v42_synth.py $(TAG)
	$(PYTHON) scripts/collect_v42.py $(TAG) --sim-tag $(SIM_TAG)
route-common:
	$(PYTHON) scripts/v42_route.py $(TAG)
	$(PYTHON) scripts/collect_v42.py $(TAG)_route --route --sim-tag $(SIM_TAG)
freeze-common:
	$(PYTHON) scripts/verify_v42_routed_rom.py $(TAG)_route
	vivado -mode batch -nolog -nojournal -source experiments/v4.2/freeze.tcl -tclargs $(TAG)_route > build/v4.2/$(TAG)_freeze.log 2>&1
report-v42:
	$(PYTHON) scripts/report_v42.py
reproduce-v42:
	$(PYTHON) scripts/reproduce_v42.py
reproduce-paper-comparison:
	$(PYTHON) scripts/reproduce_paper_comparison.py
	$(PYTHON) scripts/reproduce_seven_profiles.py
	$(PYTHON) scripts/reproduce_autonomous.py --allow-incomplete
reproduce-slh-only:
	$(PYTHON) scripts/reproduce_slh_only.py
	$(PYTHON) scripts/report_slh_paper_optimization.py --check
