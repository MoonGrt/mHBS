# 完整顶层 112 MHz 验证

```json
{
  "passed": false,
  "failures": [
    "Timing summary did not pass",
    "Setup must be > 0"
  ],
  "period_ns": 8.928,
  "wns_ns": -0.305,
  "whs_ns": 0.089,
  "drc_errors": 0,
  "io_timing_qualified": false,
  "lut": 21451.0,
  "ff": 8225.0,
  "lutram": 1284.0,
  "bram36": 11.5,
  "dsp": 0.0,
  "equivalent_slice": 9063.475,
  "rom_audit": {
    "passed": true,
    "cells": 256,
    "mapping_sha256": "569fd435d575a987b380f4d3c4bd013ed6b3fefcfbbba5c76b80dd9454aa1b67"
  },
  "requested_frequency_mhz": 112,
  "validated_frequency_mhz": null,
  "scope": "Whole internal top including ROM and signature storage; external I/O not signed off"
}
```

综合分层：synthesis/slh_128f_sign/hierarchical.rpt

布线分层：route/hierarchical.rpt
