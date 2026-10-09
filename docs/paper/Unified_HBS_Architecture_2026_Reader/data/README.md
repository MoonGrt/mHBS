# 补充数据说明

这些文件于 2026-09-24 从本地论文与当日 μHBS 实现结果整理。

## 论文原始数据

- `paper_tables.json` 与 `table1/2/5/6/7.csv`：原文报告值。Table 7 共 29 行，引用工作只按本论文转录。
- JSON 中 null、CSV 中空字段代表原文空白或短横线，不代表零。
- Table 7 合并资源/频率单元格已展开；未显式列出的 h=10 来自原脚注。Table 6 带父子层次，不能将子实例与父实例重复求和。
- `*_atp_display_raw` 是表格显示值，未被解释为 Slice·ms；`paper_recomputed.*` 才是使用明确公式得到的派生数据。
- `source_page_*.txt` 是相关 PDF 页的原生文本提取，保留排版/文本提取局限，不替代原 PDF 和原图。

## 派生数据

- `paper_recomputed.*`：7-series 等效面积与 Table 5 七个配置的 ATP 重算；同时保留报告时间和周期/108 MHz 换算值。
- `uhbs_comparison.*`：当前实现与论文三个对应点的描述性数值比值，全部为 NON_STRICT。
- 公式：等效 Slice = LUT/4 + FF/8 + BRAM×232.4 + DSP×102.4；ATP = 等效 Slice×时间(ms)。

## 当前实现快照

- `uhbs_current_snapshot.json`、`uhbs_model_gate_snapshot.json` 及 `verification/` 来自 μHBS 项目，属于外部结果，非论文原始数据。
- 这些快照内部的 RTL、checkpoint 和源码路径以原 μHBS 项目根目录为基准；本目录没有复制大型 DCP 或全部 RTL。
- 完整比较报告中的 Markdown 链接已按当前位置调整。归档日期之后的项目改动不自动更新这些快照。
- `supplement_manifest.json` 保存论文 PDF 摘要、表格来源锚点、裁切坐标和补充文件摘要。
