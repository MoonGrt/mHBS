# Launch capacity subunit reproduction

Run from `reproduce/`, with Verilator 5.008 available. All commands execute the exact U3 frozen recipe, SHA recorded in SOURCE_BINDING.json. These are module KAT/oracle tests, not complete executor/Common regressions. No detailed simulation logs are archived.

```sh
python3 scripts/check_recipes.py --pipeline 4 --unroll 1 --shared-state 1
python3 scripts/check_recipes.py --pipeline 12 --unroll 1 --shared-state 1
python3 scripts/check_recipes.py --pipeline 4 --unroll 1 --shared-state 0
python3 scripts/check_recipes.py --pipeline 2 --unroll 12 --shared-state 1
mkdir -p build/launch_reset/obj
verilator --binary --timing -O3 -j 2 -Wno-fatal --top-module tb_recipe_reset -GPIPELINE=4 -GUNROLL=1 -GSHARED_STATE=1 --Mdir build/launch_reset/obj rtl/hash/keccak.sv rtl/hash/shake-recipe.sv rtl/hash/sha256.sv rtl/hash/sha2-recipe.sv tb/tb_recipe_reset.sv
build/launch_reset/obj/Vtb_recipe_reset +VECTOR=build/recipe_check/P4U1_shared1/recipes.mem +COUNT=459
```

Each command passes 459 independent hashlib cases (2295 total); each run consumes 914 stream launches including 549 nonzero capacities. Reset-pending count is 1 in the reset bench. Production stream stalls are covered; legal stream-launch recycle stalls were 0. Original raw logs remain under tmp/t2_launch_candidate/build/, with their SHA in LAUNCH_VALIDATION.json.
