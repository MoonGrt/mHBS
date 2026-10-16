# Direct streaming permutation input

Only the scheduled P>1 SHAKE path changes. `baseline.sv` is the captured U5 recipe; `candidate.sv` and `stream_direct.patch` contain the candidate. The scalar P1 implementation is byte-identical. Production RTL was not changed and no Vivado/whole-core job was started by this review.

## Datapath and cycle effect

The previous elastic launch register accepted both fixed formatted blocks and completed streaming sponge states. Streaming input was therefore copied through a 1088-bit normal/fixed mux and a launch cycle despite already being fully registered in the sponge. The candidate keeps the launch register exclusively for fixed blocks and lets a normal streaming permutation enter stage 0 directly.

For SHARED_STATE=1, the existing final retained stage register is the sponge itself. The stage-0 state mux chooses `finished_state` for either recycling or direct stream issue, and `{512'd0,launch_state}` for fixed input. This reuses the existing 1600-bit feedback/input mux rather than adding a second stream input mux. Private state uses the required separate sponge input mux. The launch mode flag and its capacity selector disappear; fixed capacity is always zero. P2's early prefetch-local source fixed flag is consequently constant 1 for a buffered launch; stream issue is not included in that fixed prefetch source-valid qualifier.

A streaming permutation begins exactly one clock sooner: the final absorb edge writes the sponge and changes hash_state to HASH_RUN; on the following cycle the now-stable complete sponge is consumed directly by stage 0 and `sent` is set. Previously this cycle copied it into launch, and stage 0 started one further cycle later. This removes one launch wait per streaming permutation. The actual end-to-end Sign reduction must still be measured because caller stalls and concurrent producer work can mask local latency reductions. Fixed requests keep their existing launch cycle and scheduler timing. No Hash or permutation invocation is removed.

## Ownership, modes and reset

`stream_issue = !engine_mode && normal_valid && ready && !launch_valid`. Thus a recycle has priority, and an already buffered fixed launch has priority over new normal input. Fixed intake still obeys the same elastic `launch_ready` predicate. It now receives only `engine_mode && batch_perm_valid`; normal traffic cannot allocate or overwrite launch state. Fixed launch tags remain intact across recycle stalls.

Streaming requests already serialize absorb and permutation through HASH_WAIT_BLOCK/HASH_RUN and `sent`. A stream permutation cannot launch twice: its issue edge sets `sent`; completion clears it while HASH_RUN transitions to HASH_WAIT_BLOCK or HASH_IDLE. Stream base starts at round 0; only recycle advances base by P*U. The stream tag is set to zero and stage_fixed is zero; fixed requests retain tag and stage_fixed=1. All following stages and 24-round traversal logic are unchanged.

Legal mode transitions drain fixed contexts/results and launch work before streaming absorption, as required by the preexisting shared-state write assertion and executor ownership. This change does not add a mechanism for mixing independent stream and batch jobs. Simulation assertions check that stream issue sees no old stage metadata, no simultaneous sponge write, and the exact completed sponge at stage 0. The private-state compatibility path is tested, but does not claim unsupported concurrent mixed-mode jobs.

Reset clears launch_valid, recycle, sent, stage_valid, hash_state and outer stream/fetch validity, so old data/tags cannot create an event. Intermediate datapath bits may still advance as before; their metadata are invalid. The first absorb of a replay clears the sponge before building the new rate. Neither launch nor sponge payloads need a new reset fanout.

For a 136-byte rate tail, the final 8-byte absorb and running_last capture occur before HASH_RUN. Direct issue is only possible on the next edge, after that write commits. Multi-block capacity remains in the sponge; unlike fixed launch, it is not forced to zero. The hash/permutation counters still count the unchanged completion events.

## Validation completed

Four independent hashlib recipe checks pass: shared state P2U1/P4U1/P12U1, and private state P4U1. Each covers 459 cases, 15 supported recipe shapes, n=16/24/32 where appropriate, all message lengths and long lists in the existing recipe test, q/address boundaries, inter-case reset and consecutive requests, response backpressure, and exact digest/capture/Hash/permutation checks. Per group the explicit input-length 135/136/137 boundaries occur 7/5/5 times. This is recipe-level verification, not full Sign or whole-core validation.

The direct-input assertions observed per group: 134 fixed launches, 914 direct stream launches, including 549 nonzero-capacity launches. Each group's stream stall counter is 13725 cycles. This confirms multi-block streams reuse their nonzero capacity rather than being treated as fixed zero-capacity inputs. In-flight reset behavior above is audited from the unchanged metadata reset path; this particular KAT performs resets between requests, not a new mid-permutation reset test.

Raw KAT compile/run logs remain in this tmp run directory. `VALIDATION.json` records source identities, fixture shared-state settings, coverage and summaries. No area, final frequency, full-core cycle or ATP improvement is claimed from these KATs.

## V7 archive supplement

The final recipe SHA is byte-identical to the complete V7 frozen recipe in SOURCE.json and rtl.tar.gz. All additional compiled RTL dependencies, the independent hashlib check script, and the default shared-state testbench match the same frozen SOURCE manifest. The private-state fixture differs only in SHARED_STATE=0. Verification is still recipe-level and does not imply the full V7 executor/Sign snapshot was tested by this subunit runner.

Supplemental checks also pass: shared P4U1 with SYNTHESIS defined, shared P2U12 (one traversal of 24 rounds), and P1U1 elaboration. Together the six KAT groups total 2754 cases; P1's complete scalar implementation is byte-identical to U5 and passes elaboration. P1 was not re-run through the full recipe vector set for this change.

Historical build/recipe_check/P4U1 and P12U1 logs contain producer stall cycles only, with no total clock cycle count or source SHA. Their paths, SHA and visible summaries are recorded; total-cycle before/after values are explicitly null. The difference in producer stalls must not be described as total latency reduction. Removal of one launch wait per streaming permutation is a structural attribution; full Sign cycle reduction is measured by the parent experiment runner.

Run python3 reproduce.py to verify evidence SHA, extract the existing frozen RTL tar into temporary directories and reproduce the six recipe KAT groups plus P1 elaboration. No mutable production RTL is read. Compile and simulation detail logs are not archived here; raw logs remain in the tmp run locations recorded in VALIDATION.json.
