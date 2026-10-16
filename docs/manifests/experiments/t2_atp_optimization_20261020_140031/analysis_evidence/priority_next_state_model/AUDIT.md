# Registered priority publication model

Evidence type: exhaustive standalone Python transition model. No RTL is executed. This cannot replace complete source-bound candidate regressions.

The original queue update order is: clear the published old-priority slot; set an accepted zero-work slot; set a completed slot. Later sets win over the clear. The proposed next-mask is computed in that order, and both awaiting mask and priority(next-mask) register on the same edge. Therefore the current registered tag always equals priority(current mask). Held payload publication remains on its original edge, after the completing bank write is visible. Reset clears mask and tag to zero. Empty mask does not publish a payload. Backpressure retains the held payload while a newly arriving lower tag can change only the queued priority.

All 1,385,320 combinations across P2/P4/P12 pass, including simultaneous clear/set at one slot, both sets, publish disabled, and empty masks. The target experiment and exact frozen recipe identity are in SOURCE_BINDING.json; U3 is prospective analysis only, whereas U4 contains the modeled scheme.

Reproduce:

```sh
python3 audit_priority_next_state.py --output reproduced_result.json
```
