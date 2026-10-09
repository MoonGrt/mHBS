#!/usr/bin/env python3
"""Attach the audited 2026-09-24 supplement without regenerating translations."""
from pathlib import Path
import json


def apply_supplement(root: Path) -> None:
    manifest_path = root / 'data/supplement_manifest.json'
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text())
    paper = root / 'paper.md'
    text = paper.read_text()
    navigation = '''## 核对后的表格与数据补充（2026-09-24）

- [表格转录、数据与口径核对](Extracted_Data_and_Analysis.md)：Table 1/2/5/6/7 的 Markdown、CSV/JSON 与原文重算。
- [当前 μHBS 与论文的全面对比](UHBS_Comparison_2026-09-24.md)：独立实现的结果快照，全部跨实现比值为 NON_STRICT。
- [补充来源与文件摘要](data/supplement_manifest.json)。原文报告值、派生计算、外部实现结果分开保存。

'''
    if '## 核对后的表格与数据补充（2026-09-24）' not in text:
        text = text.replace('## 页面索引', navigation + '## 页面索引', 1)
    for number in (1, 2, 5, 6, 7):
        anchor = f'![Table {number}](assets/table{number}.png)'
        link = f'**核对补充：** [可复制表格、数据与说明](Extracted_Data_and_Analysis.md#audit-table{number})。'
        if link not in text:
            text = text.replace(anchor, anchor + '\n\n' + link, 1)
    # Formatting-only repairs to three inherited pseudo-math strings.
    replacements = {
        '(len=133, ω=2, h=10)': r'($\mathrm{len}=133,\ \omega=2,\ h=10$)',
        '(is_last_blk = 1)': r'($\mathrm{is\_last\_blk}=1$)',
        '(A = 0)': r'($A=0$)',
    }
    for before, after in replacements.items():
        text = text.replace(before, after)
    paper.write_text(text)
    path = root / 'source_map.json'
    source_map = json.loads(path.read_text())
    source_map['supplements'] = [manifest]
    for figure in source_map['figures']:
        if figure['id'] in manifest['crop_updates']:
            update = manifest['crop_updates'][figure['id']]
            figure['bbox'] = update['bbox_pixels_120dpi']
            figure['bbox_units'] = 'pixels at 120 dpi'
            figure['crop_verified'] = '2026-09-24'
    path.write_text(json.dumps(source_map, ensure_ascii=False, indent=2) + '\n')
    path = root / 'translation_notes.md'
    notes = path.read_text()
    if '## Audited supplement — 2026-09-24' not in notes:
        notes += '''
## Audited supplement — 2026-09-24

- Added `Extracted_Data_and_Analysis.md`, raw Table 1/2/5/6/7 CSV/JSON, separate recomputed values, and native text for PDF pages 9, 16–19.
- Table 7 includes all 29 rows as reported by this paper; cited works were not independently revalidated. Missing values remain null; merged cells and the h=10 default are explicitly expanded.
- Recropped Table 1, Table 2 and Table 5 from the original PDF at 120 dpi; missing labels/bottom rows are now visible. Existing T001/T002/T005 anchors are retained. Updated build crop coordinates preserve these repairs.
- Table 2 h denotes subtree height; h*d is derived total height. Table 1 n is bytes; Table 2 n is bits. Neither units nor cycle/time/ATP inconsistencies are silently corrected in raw data.
- Added `UHBS_Comparison_2026-09-24.md` and current-result evidence snapshots. These are external analysis, not paper-authored text or measurements; all comparisons retain NON_STRICT limitations.
- Converted three inherited parenthesized pseudo-math spans to inline math without changing their values or the original source-map text.
- `apply_supplement.py` restores navigation, source-map supplement metadata and these notes after reader regeneration. It does not regenerate or replace bilingual paragraphs.
- Table 3/4 were not newly transcribed; the pre-existing full reader and assets remain available. Other existing translation uncertainties are unchanged.
'''
    path.write_text(notes)


if __name__ == '__main__':
    apply_supplement(Path(__file__).resolve().parent)
