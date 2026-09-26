SHELL := /bin/bash
PYTHON ?= python3
VERILATOR ?= verilator
PROFILE ?= all
OPERATION ?= all
SWAP ?= 0
TAG ?= external_v42
SIM_TAG ?= $(TAG)
UHBS_RTL := $(shell cat manifests/v42_sources.txt)

.PHONY: all test compile-microcode lint rtl-unit-test rtl-profile-test rtl-all-profiles rtl-test rtl-verification synth-common route-common freeze-common report-v42 reproduce-v42
all: rtl-test
test: compile-microcode
compile-microcode:
	$(PYTHON) scripts/verify_v42_external_models.py
lint:
	$(VERILATOR) --lint-only --timing -Wno-fatal -Wno-WIDTH -Wno-UNOPTFLAT --top-module uhbs_top $(UHBS_RTL)
rtl-unit-test:
	$(PYTHON) scripts/verify_v42_external_units.py
rtl-profile-test:
	$(PYTHON) scripts/v42_external_flow.py sim --tag $(TAG) --profile $(PROFILE) --operation $(OPERATION) --swap $(SWAP)
rtl-all-profiles:
	$(MAKE) rtl-profile-test PROFILE=all OPERATION=all
rtl-test: rtl-unit-test rtl-all-profiles
rtl-verification:
	$(PYTHON) scripts/verify_v42_external_rtl.py $(TAG)
	$(PYTHON) scripts/v42_external_flow.py sim --tag $(TAG) --partition
synth-common:
	$(PYTHON) scripts/v42_external_synth.py $(TAG)
	$(PYTHON) scripts/collect_v42_external.py $(TAG) --sim-tag $(SIM_TAG)
route-common freeze-common:
	$(error 布局修订3本轮只提供post-synth流程；旧布线请使用366b614或封存源码)
report-v42:
	$(PYTHON) scripts/report_v42_external.py
reproduce-v42:
	$(PYTHON) scripts/reproduce_v42.py
	$(PYTHON) scripts/reproduce_v42_external.py
reproduce-paper-comparison:
	$(PYTHON) scripts/reproduce_paper_comparison.py
	$(PYTHON) scripts/reproduce_seven_profiles.py
	$(PYTHON) scripts/reproduce_autonomous.py --allow-incomplete
reproduce-slh-only:
	$(PYTHON) scripts/reproduce_slh_only.py
	$(PYTHON) scripts/report_slh_paper_optimization.py --check
