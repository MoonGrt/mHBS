# ablation 组件目录整理

三种设计在原 mHBS 工作目录内按组件组织：`rtl/i`、`rtl/c`、`rtl/t` 与 `image/i`、`image/c`、`image/t`。根目录不再保留 i/c/t 三套完整工程，也没有新建 worktree。共用模型、脚本、测试台及文档；实现差异分别留在 `model/variants/`、`tb/{i,c,t}/`。

## 构建和镜像

`rtl/<设计>/sources.txt` 选择生产 RTL，根 sources.txt 默认 i。设置 `MHBS_DESIGN=i|c|t` 或运行 `scripts/ablation.sh <设计> ...`，始终从项目根目录构建。镜像按后端与参数放在 `image/<设计>/<shake|sha2>/<参数>/`；输入和参考数据位于 `tb/vectors/<设计>/`。仿真在忽略的 build 目录临时组合两者，支持原有自定义故障镜像。

各设计的 ABI、指令容量、ROM 字节、算法、端口和执行流程保持不变。32 个 RTL/header 中27个字节完全一致，5个只修改 include 或 top 默认 ROM 路径；规范化这些路径后全文相同。[RTL 对照](../RTL_PATH_AUDIT.json)记录逐文件证据。

## 验证

| 检查 | 结果 |
|---|---|
| 三设计、两后端全部规范镜像 | 60组重新生成并逐字节一致 |
| SLH128f／XMSS h10／LMS h10 Verify | 18项全部通过，周期、Hash/块数、前像/结果指纹及动态统计与原基线精确一致 |
| top 完整 SLH128f Sign 与签名缓存 | 三设计×两后端，共6项通过；调试开启、签名缓存开启视图 |
| 固定及流式配方 | 每设计 SHAKE459项、SHA2 345项全部通过 |
| i/c 软件控制指令 | 两后端×正常/综合视图各通过，共8组 |
| 删除旧根 i/c/t 后再次运行 | 60组镜像及18项 Verify 再次通过 |

这是目录兼容性检查，未重新执行完整参数三操作验收。没有执行 h16/h15/h20 的完整 Keygen/Sign。详细日志保留在 build，归档仅保留[验证摘要](../VALIDATION_SUMMARY.json)和[入口检查摘要](../ENTRYPOINT_VALIDATION.json)。

## 保留与范围

原32,603个导入文件均有[旧→新路径及校验映射](../PATH_MAPPING.json)。相同历史文档合并为一份；差异文档及原索引放到 docs/designs。被替换的历史工具与元数据压缩保存，原字节身份保留；不再作为活动构建入口。仅路径/元数据调整的原文件另行归档。原运行日志与缓存移入 `build/component_layout_previous/{i,c,t}`，见[记录](../RUNTIME_RELOCATION.json)。

本次没有启动综合或布局布线，未新增面积、频率或 ATP 测量。原分层面积及时序报告保留在各历史实验目录，仍绑定原冻结源码。[源码身份](../SOURCE.json)、[冻结RTL](../frozen_rtl.tar.gz)和[冻结镜像](../frozen_images.tar.gz)随本次归档保存。
