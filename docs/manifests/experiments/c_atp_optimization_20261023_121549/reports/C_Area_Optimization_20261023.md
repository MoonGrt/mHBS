# c 实现面积优化：SHAKE／SHA2

更新时间：2026-10-23T12:40:22+08:00；8项面积候选综合全部结束：True。

范围：K1U1、单 Hash 通道、c 的 RTL CHAIN＋软件树控制；面积取同后端的 common。
共同设置：Vivado 2025.2、xc7a200tffg1156-3、OOC、2线程、默认时序驱动综合、10ns诊断约束。
等效Slice=LUT/4+FF/8；不含程序／模板／描述符ROM及签名缓存。

用户已改为面积优先、仅综合。本轮未启动布局布线；10ns综合WNS只用于诊断，不能证明100MHz或150MHz达标，也不代表实际Fmax。

| 阶段 | 后端 | 状态 | LUT | FF | BRAM | DSP | 等效Slice | 相对历史c | 综合WNS/ns | 验证／取舍 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| 历史c C1 | shake | 历史已测 | 20,099 | 6,324 | — | — | 5,815.250 | 基线 | — | 原冻结设计的历史证据 |
| combined | shake | passed | 19,525 | 6,345 | 0.000 | 0 | 5,674.375 | -2.423% | -3.125 | 组合候选淘汰：SHA2面积回退 |
| area_banks | shake | passed | 19,030 | 6,224 | 0.000 | 0 | 5,535.500 | -4.811% | -3.602 | 仅综合，未仿真 |
| area_banks_shared | shake | passed | 19,343 | 6,265 | 0.000 | 0 | 5,618.875 | -3.377% | -3.166 | 仅综合，未仿真 |
| area_legal_decode | shake | withdrawn | — | — | — | — | — | — | — | 语义审计发现回退，已撤回 |
| area_legal_bytes | shake | passed | 19,030 | 6,224 | 0.000 | 0 | 5,535.500 | -4.811% | -3.602 | 已选用；仅综合，未仿真 |
| area_cursor | shake | passed | 18,989 | 6,213 | 0.000 | 0 | 5,523.875 | -5.011% | -3.292 | 仅综合，未仿真 |
| 历史c C1 | sha2 | 历史已测 | 17,198 | 7,273 | — | — | 5,208.625 | 基线 | — | 原冻结设计的历史证据 |
| combined | sha2 | passed | 17,758 | 7,072 | 0.000 | 0 | 5,323.500 | +2.205% | -4.152 | 组合候选淘汰：SHA2面积回退 |
| area_banks | sha2 | passed | 17,038 | 6,955 | 0.000 | 0 | 5,128.875 | -1.531% | -3.055 | 仅综合，未仿真 |
| area_banks_shared | sha2 | passed | 17,540 | 6,986 | 0.000 | 0 | 5,258.250 | +0.953% | -3.292 | 仅综合，未仿真 |
| area_legal_decode | sha2 | withdrawn | — | — | — | — | — | — | — | 语义审计发现回退，已撤回 |
| area_legal_bytes | sha2 | passed | 16,920 | 6,947 | 0.000 | 0 | 5,098.375 | -2.117% | -2.920 | 已选用；仅综合，未仿真 |
| area_cursor | sha2 | passed | 17,040 | 6,920 | 0.000 | 0 | 5,125.000 | -1.606% | -3.600 | 仅综合，未仿真 |

combined 合并了控制／周期和配方优化，但SHA2等效面积相对历史c约增加2.2%，故不作为最终面积候选。后续面积候选按相同设置仅综合；未仿真，功能和周期仍待验证。

area_legal_decode 曾将SHA2 profile_code固定为0，但合法自定义stateful程序仍可读取FORS_TARGET上下文；该折叠改变可观察语义，已撤回。该阶段不计入等待任务、不作为候选；撤回原因、冻结源码及已产生日志仍保留。

area_legal_bytes 保留原始 profile_code=config_code[1:0]，仅简化SHA2合法配置的节点字节数选择：stateful为32字节、SLH为16字节。它旨在保持全部合法ROM行为；本阶段仅综合，尚未经过仿真验收，不声明功能等价已验证。

area_cursor 基于私有游标生命周期审计，将互斥使用的 transform_index／chain_cursor／lt_cursor 合并为8位 work_cursor，供消息半字节选择等逻辑复用。该候选未改变预定调度或外部指令集；仅综合，功能和周期仍未仿真验证。

候选未得到完整测量周期及布线频率，因此本报告不填写候选ATP，也不把历史周期移植到未验证候选。

## 最终选择

以下按运行目录 SELECTION.json 原样记录：

```json
{
  "selected_stage": "area_legal_bytes",
  "reason": "Both backend areas improve versus historical c; among tested common-executor variants this has the smallest sum of SHAKE+SHA2 equivalent Slice. Cursor sharing saves 11.625 Slice on SHAKE but costs 26.625 Slice on SHA2.",
  "base_ref": "ablation",
  "base_commit": "240ee5677253a8817dae8e9df303efd751c55afd",
  "branch": "codex/ablation-c-atp-20261023",
  "worktree": "/tmp/mhbs-ablation-c-atp-20261023",
  "copied_to_mutable_rtl": true,
  "mutable_rtl_matches_measured_source": true,
  "selected_rtl_sha256": {
    "rtl/c/sources.txt": "9562ad2e0fc21630152028275c42a09ad784649a3cf15d1f84286bd6291822a7",
    "rtl/c/hash/keccak.sv": "fcd027336e194d1f2b9d3d67f3abf5792346adf9ef8fa572f3b66a5a34458769",
    "rtl/c/hash/sha2-recipe.sv": "1bdfce52058432358036cfc17d9018ea405f24d6df46ba4d2c5b2c71b50652e4",
    "rtl/c/hash/shake-recipe.sv": "bc86e9ccfbae76cf9fc93e77ed7007473e98aab4598ef80568cb438da6566805",
    "rtl/c/hash/sha256.sv": "611775b5ff93a5ab3f2785c77cc38f5f604b9153f65d1e81a00e14ea349a7b0a",
    "rtl/c/memory/signature.sv": "98ce7287800ba3e073bcc5a08919a4f899b7827a3e7387b3d3d828c4ad787149",
    "rtl/c/memory/value.sv": "f608604bd5b5cd4cbc8c20d16135b6399e154e647ef0e78cfb4e1e34d143dbd9",
    "rtl/c/top/common.sv": "f5ee9bf61b72dc7a4d847b38dd1dbaa4fdadfe3a6eb91a6203d1c67e7180ab4b",
    "rtl/c/top/top.sv": "9ded60b8d51bc575e21f3434a6b5f4482713f137468904757be65caa4d4cff11",
    "rtl/c/executor/instructions.svh": "d869832ea07b0994b6d91851b1880b67f098cb09e17b895cbfeb8e15c86d220c",
    "rtl/c/executor/executor.sv": "9e74d96864ee0454e42bc2f08058508b4b1e54daecae522b7d84539bfa8aec1a",
    "rtl/c/executor/sequencer.sv": "3469b5c6e75befe8c96ebd93728a54c1c30346d0fdb0bad78058de700fa55a17"
  },
  "area": {
    "shake": {
      "baseline_equivalent_slice": 5815.25,
      "equivalent_slice": 5535.5,
      "change_pct": -4.810627230127684
    },
    "sha2": {
      "baseline_equivalent_slice": 5208.625,
      "equivalent_slice": 5098.375,
      "change_pct": -2.1166814658379107
    }
  },
  "scope": "K1U1 common; Vivado2025.2 xc7a200tffg1156-3 OOC100MHz2threads; excludes ROM/signature cache",
  "validation": "Synthesis plus source-lifetime/ISA audit only; no new simulation after user changed scope to area-only. Initial combined candidate had partial checks; these are not final-candidate validation.",
  "place_route_started": false,
  "selected_at": "2026-10-23T12:39:01.814266+08:00"
}
```

## 已有检查及适用范围

combined 的部分配方／整核检查已完成，随后测试任务按用户要求停止；不得声称44项回归全部通过。最新面积候选按用户要求未执行仿真。

combined 已完成 top 签名视图检查 6/8 项：

- `synthesis0_signature0`：`TOP_SIGNATURE_PASS bytes=17088 hashes=104937 permutations=105641`。
- `synthesis0_signature0_sha2`：`TOP_SIGNATURE_PASS bytes=17088 hashes=104925 permutations=211432`。
- `synthesis0_signature1`：`TOP_SIGNATURE_PASS bytes=17088 hashes=104937 permutations=105641`。
- `synthesis0_signature1_sha2`：`TOP_SIGNATURE_PASS bytes=17088 hashes=104925 permutations=211432`。
- `synthesis1_signature0`：`TOP_SIGNATURE_PASS bytes=17088 hashes=104937 permutations=105641`。
- `synthesis1_signature0_sha2`：`TOP_SIGNATURE_PASS bytes=17088 hashes=104925 permutations=211432`。

运行器提供的验证范围摘要：

```json
{
  "full_regression": "stopped at user request; area-only synthesis",
  "completed_combined_cases": [
    "shake/slh_128f/sign passed 2851106",
    "sha2/slh_128f/sign passed 15302246",
    "shake/xmss_h10/sign passed 86578433",
    "shake/lms_h10/sign passed 28538019",
    "shake/slh_128f/verify passed 211384",
    "shake/xmss_h10/verify passed 52795",
    "shake/lms_h10/verify passed 15803",
    "shake/slh_128f/keygen passed 111609",
    "shake/xmss_h10/keygen passed 86538133",
    "shake/lms_h10/keygen passed 28518369",
    "shake/slh_128s/keygen passed 7144929",
    "shake/slh_128s/sign passed 60803892",
    "shake/slh_128s/verify passed 77483",
    "shake/slh_192f/keygen passed 163001",
    "shake/slh_192f/sign passed 5172296",
    "shake/slh_192f/verify passed 292973",
    "shake/slh_192s/keygen passed 10434017",
    "sha2/xmss_h10/sign passed 497867033"
  ],
  "area_candidates": "synthesis and read-only code audit only; no new full simulation requested"
}
```

## 冻结与归档

各阶段保留其自身 frozen_rtl.tar.gz、冻结源码 SOURCE.json，以及综合 hierarchical、timing、utilization、settings、debug_audit 和 Vivado日志。缺项记录在JSON；不使用当前RTL替换历史快照。
不归档DCP或仿真明细日志；原始运行日志仍在build目录。MD／JSON报告与证据路径见本实验 ARTIFACTS.json。
后台模式每60秒检查一次，8项新候选综合结束后退出，不持续重写完成报告。
