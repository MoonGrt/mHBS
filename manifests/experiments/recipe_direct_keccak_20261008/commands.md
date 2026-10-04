# Executed commands

Run from repository root; logs are kept in this experiment and `build/recipe_direct_keccak_20261008`.

```sh
python3 scripts/verify_v42_units.py
python3 scripts/verify_kpu_round_decode.py --out build/recipe_direct_keccak_20261008/rounds
python3 -m unittest tests.test_unified_rtl_contract tests.test_v42_external_flow tests.test_v42_external_route
python3 scripts/verify_v42_verify.py recipe_direct_keccak_20261008_v2 --quick
python3 scripts/v42_external_flow.py sim --tag recipe_direct_keccak_kg_20261008_v2 --profile slh_128f --operation keygen
python3 scripts/run_kpu_atp_candidate.py --experiment recipe_direct_keccak_20261008 --candidate direct --mandatory --best 35966.91068 --cycle-reference manifests/experiments/recipe_direct_keccak_20261008/baseline/simulation.json
```

The candidate command runs all four sign simulations, four syntheses, stats-off/replay/partition/default/fault checks, and `verify_lup_pipeline.py`. No routing command was used. For a new run, use fresh candidate/tag names; the existing snapshots are immutable. Final migrated test sources are in `validation_source/source_snapshot.tar.gz`; see its recorded test-only correction relative to the synthesis snapshot.
