SHELL := /bin/bash
PYTHON ?= python3
VERILATOR ?= verilator
PROFILE ?= all
OPERATION ?= all
SWAP ?= 0
TAG ?= external_v42
SIM_TAG ?= $(TAG)
MHBS_RTL := $(shell cat manifests/v42_sources.txt)

.PHONY: all test verify contract-test compile-microcode lint rtl-unit-test rtl-profile-test rtl-all-profiles rtl-test rtl-verification synth-common route-common freeze-common report-v42 reproduce-v42 reproduce-paper-comparison reproduce-slh-only
all: test
# Keep generation and unit evidence ahead of snapshot capture, including make -j.
test:
	$(MAKE) contract-test lint
	$(MAKE) compile-microcode
	$(MAKE) rtl-test
verify: test
	$(MAKE) rtl-verification
	$(PYTHON) scripts/verify_v42_current.py $(TAG)
contract-test:
	$(PYTHON) -m unittest tests.test_unified_rtl_contract tests.test_v42_external_flow tests.test_v42_external_route -v
compile-microcode:
	$(PYTHON) scripts/verify_v42_external_models.py
lint:
	$(VERILATOR) --lint-only --timing -Wno-fatal -Wno-WIDTH -Wno-UNOPTFLAT --top-module mhbs_top $(MHBS_RTL)
rtl-unit-test:
	$(PYTHON) scripts/verify_v42_external_units.py
rtl-profile-test:
	$(PYTHON) scripts/v42_external_flow.py sim --tag $(TAG) --profile $(PROFILE) --operation $(OPERATION) --swap $(SWAP)
rtl-all-profiles:
	$(MAKE) rtl-profile-test PROFILE=all OPERATION=all
rtl-test:
	$(MAKE) rtl-unit-test
	$(MAKE) rtl-all-profiles
rtl-verification:
	$(PYTHON) scripts/verify_v42_external_rtl.py $(TAG)
	$(PYTHON) scripts/v42_external_flow.py sim --tag $(TAG) --partition
	$(PYTHON) scripts/verify_v42_pruning.py $(TAG)
synth-common:
	$(PYTHON) scripts/v42_external_synth.py $(TAG)
	$(PYTHON) scripts/collect_v42_external.py $(TAG) --sim-tag $(SIM_TAG)
route-common:
	$(PYTHON) scripts/v42_external_route.py $(TAG)
	$(PYTHON) scripts/collect_v42_external_route.py $(TAG)
freeze-common:
	$(PYTHON) scripts/collect_v42_external_route.py $(TAG)
report-v42:
	$(PYTHON) scripts/report_v42_external_ppa.py
reproduce-v42:
	$(PYTHON) scripts/reproduce_v42.py
	$(PYTHON) scripts/reproduce_v42_external.py
	$(PYTHON) scripts/reproduce_v42_external_route.py
reproduce-paper-comparison:
	$(PYTHON) scripts/reproduce_paper_comparison.py
	$(PYTHON) scripts/reproduce_seven_profiles.py
	$(PYTHON) scripts/reproduce_autonomous.py --allow-incomplete
reproduce-slh-only:
	$(PYTHON) scripts/reproduce_slh_only.py
	$(PYTHON) scripts/report_slh_paper_optimization.py --check
