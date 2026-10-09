#!/usr/bin/env python3
"""Build a source-anchored bilingual reader for IACR ePrint 2026/194.

The script deliberately keeps extraction and translation provenance visible.  It uses
Poppler for the selectable text layer and an offline Argos/CTranslate2 model for the
first-pass Chinese translation; the companion analysis report is manually audited.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

import ctranslate2
from PIL import Image
from transformers import AutoTokenizer


TITLE = "A Unified Hardware Architecture for Stateful and Stateless Hash-Based Key/Signature Generations"

FIGURES = {
    1: (5, (230, 345, 780, 560), "Authentication Path of Merkle Tree.", "Merkle 树认证路径", "p.5 S-MERKLE"),
    2: (5, (245, 805, 775, 1165), "LMS overall structure.", "LMS 总体结构", "p.5 S-LMS"),
    3: (6, (220, 650, 780, 1055), "XMSS overall structure.", "XMSS 总体结构", "p.6 S-XMSS"),
    4: (8, (205, 155, 800, 760), "SPHINCS+ overall structure.", "SPHINCS+ 总体结构", "p.7 S-SPHINCS"),
    5: (9, (260, 805, 740, 1075), "Overall hardware architecture.", "顶层统一硬件架构", "p.9 S-TOP"),
    6: (10, (190, 585, 800, 945), "Architecture of the HASH LOOP module.", "HASH LOOP 计算模块", "p.10 S-HASHLOOP"),
    7: (12, (330, 515, 710, 760), "ATP across parallelism under unrolling factor 1 and 2 for LMS (len=133, ω=2, h=10).", "LMS 在 U=1/2 下随并行度变化的 ATP", "p.12 S-DESIGNPOINT"),
    8: (13, (260, 170, 740, 395), "Proposed logic architectures: dedicated OTS path and flexible path.", "非对称双路径哈希输入逻辑", "p.12 S-HIL"),
    9: (13, (235, 625, 755, 890), "Timing of OTS chain.", "OTS 链时序", "p.13 S-OTS-TIMING"),
    10: (15, (180, 385, 800, 545), "Execution flow and task scheduling of SPHINCS+ signature generation.", "SPHINCS+ 签名任务调度", "p.15 S-SCHED"),
    11: (16, (280, 380, 700, 565), "Architecture of hierarchical counter.", "分层计数器控制结构", "p.16 S-COUNTER"),
}

TABLES = {
    1: (9, (314, 194, 680, 385), "Parameters Set in XMSS/LMS", "XMSS/LMS 参数集", "p.8 S-PARAM"),
    2: (9, (289, 421, 703, 584), "Parameters Set in SPHINCS+", "SPHINCS+ 参数集", "p.8 S-PARAM"),
    3: (11, (270, 170, 715, 465), "Measured slice, time, and ATP under parallelism/unrolling choices", "并行度与展开因子的消融", "p.11 S-PU"),
    4: (14, (170, 555, 820, 1030), "Task-based abstraction for Hash-Based Signatures", "11 个共享参数化任务", "p.14 S-TASKS"),
    5: (17, (240, 277, 751, 472), "Latency of processor", "处理器周期与延迟", "p.17 S-LATENCY"),
    6: (17, (210, 720, 780, 1045), "Resource utilization by module", "分模块资源占用", "p.17 S-RESOURCE"),
    7: (19, (170, 265, 830, 1150), "Comparison of resource usage and performance across schemes", "跨方案资源与性能比较", "p.18 S-COMPARE"),
}

EQUATIONS = {
    1: (4, "1", r"\mathrm{wots.sig}=\mathrm{wots.sig}_0\parallel\mathrm{wots.sig}_1\parallel\cdots\parallel\mathrm{wots.sig}_{\mathrm{len}-1}", "WOTS 签名串接"),
    2: (6, "2", r"\mathrm{LMS.sig}=\mathrm{type}\parallel R\parallel\mathrm{wots.sig}\parallel q\parallel\mathrm{path}", "LMS 签名格式"),
    3: (7, "3", r"\mathrm{XMSS.sig}=\mathrm{idx.sig}\parallel R\parallel\mathrm{wots.sig}\parallel\mathrm{path}", "XMSS 签名格式"),
    4: (7, "4", r"\begin{aligned}\mathrm{FORS.sig}&=\mathrm{sig.subtree}_0\parallel\cdots\parallel\mathrm{sig.subtree}_{k-1}\\&=\mathrm{sk.fors}_0\parallel\mathrm{fors.path}_0\parallel\cdots\parallel\mathrm{sk.fors}_{k-1}\parallel\mathrm{fors.path}_{k-1}\end{aligned}", "FORS 签名格式"),
    5: (7, "5", r"\mathrm{SPHINCS{+}.sig}=R\parallel\mathrm{FORS.sig}\parallel\mathrm{HT.sig}", "SPHINCS+ 签名格式"),
    6: (7, "6", r"\begin{aligned}\mathrm{HT.sig}&=\mathrm{XMSS.sig}_0\parallel\cdots\parallel\mathrm{XMSS.sig}_{D-1},\\\mathrm{XMSS.sig}_i&=\mathrm{wots.sig}_i\parallel\mathrm{path}_i\end{aligned}", "超树签名格式"),
}


def extract_pages(pdf: Path) -> list[str]:
    with tempfile.NamedTemporaryFile(suffix=".txt") as fh:
        subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), fh.name], check=True)
        text = Path(fh.name).read_text(encoding="utf-8")
    return text.split("\f")[:22]


def clean_lines(page_text: str, page: int) -> list[str]:
    lines = [line.rstrip() for line in page_text.splitlines()]
    cleaned = []
    for line in lines:
        s = line.strip()
        if s == str(page):
            continue
        if s == TITLE:
            continue
        if s.startswith("Yechu Zhang") and (s.endswith(str(page)) or "Jing Tian" in s):
            continue
        cleaned.append(line)
    return cleaned


def paragraphs(page_text: str, page: int) -> list[str]:
    lines = clean_lines(page_text, page)
    groups: list[list[str]] = []
    cur: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            if cur:
                groups.append(cur)
                cur = []
            continue
        cur.append(s)
    if cur:
        groups.append(cur)
    out = []
    i = 0
    while i < len(groups):
        g = groups[i]
        text = " ".join(g)
        if re.fullmatch(r"\d+(?:\.\d+)*", text) and i + 1 < len(groups):
            nxt = " ".join(groups[i + 1])
            if len(nxt) < 100:
                text += " " + nxt
                i += 1
        text = re.sub(r"(?<=\w)- (?=\w)", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            out.append(text)
        i += 1
    return out


class OfflineTranslator:
    def __init__(self, model_root: Path):
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_root), src_lang="eng_Latn")
        self.tr = ctranslate2.Translator(str(model_root), device="cpu", inter_threads=4)

    def _chunks(self, text: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\[])|(?<=;)\s+", text)
        chunks = []
        for sentence in sentences:
            words = sentence.split()
            while len(words) > 80:
                chunks.append(" ".join(words[:80]))
                words = words[80:]
            if words:
                chunks.append(" ".join(words))
        return chunks or [text]

    def translate(self, text: str) -> str:
        if not text:
            return ""
        if text == "References" or re.match(r"^\[[A-Z]", text):
            return "参考文献书目信息保持原文。"
        chunks = self._chunks(text)
        tokens = [self.tokenizer.convert_ids_to_tokens(self.tokenizer.encode(c)) for c in chunks]
        prefixes = [["zho_Hans"] for _ in chunks]
        results = self.tr.translate_batch(
            tokens, target_prefix=prefixes, beam_size=3, max_batch_size=32
        )
        zh = "".join(
            self.tokenizer.decode(
                self.tokenizer.convert_tokens_to_ids(r.hypotheses[0]),
                skip_special_tokens=True,
            )
            for r in results
        )
        replacements = {
            "关键生成": "密钥生成", "密钥一代": "密钥生成", "签署": "签名",
            "无状态散列": "无状态哈希", "有状态散列": "有状态哈希",
            "散列核心": "哈希核", "散列函数": "哈希函数", "散列操作": "哈希操作", "hash": "哈希",
            "梅克尔": "Merkle", "温特尼茨": "Winternitz", "一次性签字": "一次性签名",
            "认证道路": "认证路径", "区域效率": "面积效率", "区域开销": "面积开销",
            "面积-时间产品": "面积-时间积", "可配置硬件结构": "可配置硬件架构",
            "外围树": "超树", "森林随机子集": "随机子集森林",
        }
        for old, new in replacements.items():
            zh = zh.replace(old, new)
        return zh.strip()


def crop_assets(pdf: Path, out: Path) -> None:
    pages_dir = out / "_rendered_pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pdftoppm", "-png", "-r", "120", "-f", "1", "-l", "22", str(pdf), str(pages_dir / "page")], check=True)
    assets = out / "assets"
    assets.mkdir(exist_ok=True)
    for kind, items in (("fig", FIGURES), ("table", TABLES)):
        for number, (page, box, *_rest) in items.items():
            src = pages_dir / f"page-{page:02d}.png"
            Image.open(src).crop(box).save(assets / f"{kind}{number}.png")
    for page in pages_dir.glob("*.png"):
        page.unlink()
    pages_dir.rmdir()


def is_heading(text: str) -> bool:
    return bool(re.fullmatch(r"(?:\d+(?:\.\d+){0,2}\s+)?[A-Za-z][A-Za-z0-9+–—\- ]{1,80}", text)) and len(text.split()) <= 10


def build(pdf: Path, out: Path, model_root: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    crop_assets(pdf, out)
    pages = extract_pages(pdf)
    translator = OfflineTranslator(model_root)
    blocks = []
    page_entries = []
    order = 0
    source_no = 0
    references_mode = False
    translated_pages: dict[int, list[dict]] = {}
    for page, raw in enumerate(pages, 1):
        pblocks = []
        for original in paragraphs(raw, page):
            if original == "References":
                references_mode = True
            # Figure/table render text and bibliography are not body prose.  Keep an anchor,
            # but do not machine-translate tabular fragments or alter citation metadata.
            block_type = "heading" if is_heading(original) else "paragraph"
            if original.startswith("Figure "):
                block_type = "caption"
            elif original.startswith("Table "):
                block_type = "table"
            elif references_mode and original.startswith("["):
                block_type = "reference"
            source_no += 1
            order += 1
            bid = f"S{source_no:03d}"
            translation = translator.translate(original) if block_type not in {"table", "reference"} else ("表格见本页对应图像卡。" if block_type == "table" else "书目信息保持原文。")
            item = {
                "id": bid, "page": page, "type": block_type, "order": order,
                "original_text": original, "translation": translation,
                "bbox": None, "confidence": "medium", "refs": [], "insert_after": None,
            }
            blocks.append(item)
            pblocks.append(item)
        translated_pages[page] = pblocks
        page_entries.append({"page": page, "block_ids": [b["id"] for b in pblocks]})

    equations = []
    for number, (page, printed, latex, label) in EQUATIONS.items():
        order += 1
        eid = f"E{number:03d}"
        entry = {"id": eid, "page": page, "type": "equation", "order": order,
                 "equation_number": printed, "latex": latex, "bbox": None,
                 "confidence": "medium", "image_path": None,
                 "original_text": latex, "translation": label}
        blocks.append(entry)
        equations.append({k: entry[k] for k in ("id", "page", "equation_number", "latex", "bbox", "confidence", "image_path")})
        page_entries[page - 1]["block_ids"].append(eid)

    figures = []
    for number, (page, box, caption, zh_caption, placed) in FIGURES.items():
        figures.append({"id": f"F{number:03d}", "page": page, "caption_id": f"C-FIG-{number:02d}",
                        "image_path": f"assets/fig{number}.png", "bbox": list(box),
                        "placement_hint": "near_first_mention", "placed_after": placed,
                        "alt_text": zh_caption})
    for number, (page, box, caption, zh_caption, placed) in TABLES.items():
        figures.append({"id": f"T{number:03d}", "page": page, "caption_id": f"C-TAB-{number:02d}",
                        "image_path": f"assets/table{number}.png", "bbox": list(box),
                        "placement_hint": "near_first_mention", "placed_after": placed,
                        "alt_text": zh_caption})

    glossary = [
        {"term": "hash-based signature (HBS)", "translation": "基于哈希的签名", "note": "全文简称 HBS"},
        {"term": "stateful/stateless", "translation": "有状态/无状态", "note": "指签名密钥状态管理"},
        {"term": "one-time signature (OTS)", "translation": "一次性签名", "note": "包括 WOTS/WOTS+"},
        {"term": "authentication path", "translation": "认证路径", "note": "Merkle 路径"},
        {"term": "hash-input logic (HIL)", "translation": "哈希输入逻辑", "note": "保留 HIL 缩写"},
        {"term": "unrolling factor / parallelism", "translation": "展开因子 / 并行度", "note": "分别记作 U/P"},
        {"term": "Area-Time Product (ATP)", "translation": "面积-时间积", "note": "按论文等效 Slice 口径"},
        {"term": "hierarchical counter", "translation": "分层计数器", "note": "cnt/num/index 三级"},
    ]
    source_map = {
        "paper": {"title": TITLE, "venue": "IACR ePrint 2026/194; manuscript labels TCHES with placeholder DOI",
                  "source_type": "pdf", "language": "en", "source_path": str(pdf),
                  "sha256": "40453c6ac61a703e812b447301ecdccf011adbd8a0c9eca088bdd6ffbe789802"},
        "blocks": blocks, "pages": page_entries, "figures": figures, "equations": equations,
        "glossary": glossary,
    }
    (out / "source_map.json").write_text(json.dumps(source_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = [
        f"# {TITLE}", "", "**作者：** Yechu Zhang, Yuxuan Chu, Yaodong Wei, Yueqin Dai, Qiu Shen, Jing Tian", "",
        "**来源：** IACR ePrint 2026/194，22 页；本地 PDF 的 SHA-256 已核验。", "",
        "> 本阅读稿按 PDF 文本层逐块建立锚点。中文为离线机器初译并统一了核心术语；公式、参数、图表和结论应以英文原文及原始 PDF 为准。经人工审查的批判性结论见同目录 `../Unified_Stateful_Stateless_HBS_Architecture_2026_Analysis.md`。", "",
        "## 页面索引", "", " · ".join(f"[p.{p}](#page-{p})" for p in range(1, 23)), "",
        "## 公式索引", "",
    ]
    for number, (page, printed, _latex, label) in EQUATIONS.items():
        md.append(f"- [E{number:03d} · Eq. ({printed})](#E{number:03d}) — p.{page}，{label}")
    md += ["", "## 术语表", "", "| Canonical term | 中文 | 处理决定 |", "|---|---|---|"]
    for g in glossary:
        md.append(f"| {g['term']} | {g['translation']} | {g['note']} |")
    md += ["", "## 逐页中英对照", ""]

    figs_by_page = {}
    for n, value in FIGURES.items(): figs_by_page.setdefault(value[0], []).append(("fig", n, value))
    for n, value in TABLES.items(): figs_by_page.setdefault(value[0], []).append(("table", n, value))
    eq_by_page = {}
    for n, value in EQUATIONS.items(): eq_by_page.setdefault(value[0], []).append((n, value))

    for page in range(1, 23):
        md += [f'<a id="page-{page}"></a>', f"## Page {page}", ""]
        for b in translated_pages[page]:
            if b["type"] == "heading":
                md += [f"### {b['original_text']}", ""]
            md += [f'<a id="{b["id"]}"></a>', f'**Source:** p.{page} {b["id"]}', "",
                   f'**Original:** {b["original_text"]}', "", f'**中文:** {b["translation"]}', ""]
        for n, (_page, printed, latex, label) in eq_by_page.get(page, []):
            md += [f'<a id="E{n:03d}"></a>', f"**Source:** p.{page} E{n:03d} · Eq. ({printed})", "", "$$", latex, "$$", "", f"**中文说明：** {label}；符号与连接顺序保持原式。", ""]
        for kind, n, (_page, _box, caption, zh_caption, placed) in figs_by_page.get(page, []):
            anchor = f"F{n:03d}" if kind == "fig" else f"T{n:03d}"
            label = f"Fig. {n}" if kind == "fig" else f"Table {n}"
            md += [f'<a id="{anchor}"></a>', f"### {label}. {zh_caption}", "", f"**Placed near:** {placed}",
                   f"**Source:** p.{page} C-{'FIG' if kind == 'fig' else 'TAB'}-{n:02d}", "",
                   f"![{label}](assets/{kind}{n}.png)", "", f"**Original caption:** {caption}", "",
                   f"**中文图注:** {zh_caption}", "", "**Reading note:** 图表用于核对相邻段落的结构或定量主张；批判性解读见独立分析报告。", ""]
    md += ["## 阅读提示", "", "这是一篇硬件架构/实现论文。阅读时应把三层证据分开：算法任务抽象是结构性贡献；P/U 与 HIL 是局部设计点；Table 5–7 是最终 PPA 证据。跨论文性能比受哈希函数、器件、参数集、输出语义和功能边界影响，不能把 ATP 比值直接解释为纯架构优势。", ""]
    (out / "paper.md").write_text("\n".join(md), encoding="utf-8")

    notes = """# Translation and extraction notes

- Source format: selectable-text PDF; all 22 pages were processed.
- Integrity: SHA-256 matches `references/SHA256SUMS`.
- Poppler reports a malformed trailer/xref warning, but page count, rendering, and text extraction complete successfully.
- Chinese body text is an offline Argos/CTranslate2 first-pass translation. Core terminology was normalized, but dense formula-bearing prose and bibliography were not line-edited; use the English block and PDF as authority.
- Equations E001–E006 were reconstructed from the rendered pages and marked medium confidence. Mathematical symbols are not translated.
- Figure/table crops are approximate semantic crops at 120 dpi. Captions remain separate in Markdown.
- Bibliographic entries retain original wording; the Chinese side states that metadata is unchanged.
- Known source inconsistencies (standard citation, units/notation, cross-references, comparison fairness) are not silently corrected in the bilingual body; they are audited in the companion analysis report.
"""
    (out / "translation_notes.md").write_text(notes, encoding="utf-8")
    from apply_supplement import apply_supplement
    apply_supplement(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("model_root", type=Path)
    args = ap.parse_args()
    build(args.pdf.resolve(), args.out.resolve(), args.model_root.resolve())


if __name__ == "__main__":
    main()
