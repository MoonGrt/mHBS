#!/usr/bin/env python3
"""Plot the latest adopted eight cycle partitions on one common scale."""
import json
from pathlib import Path
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import MultipleLocator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'qa'))
from audit_panel_alignment import require_matplotlib_panel_alignment

COLORS = {'Hash': '#4C72B0', 'Transfer': '#D89B52', 'Remaining': '#BEC4CC'}
FIGURE_WIDTH_MM = 183
FIGURE_HEIGHT_MM = 125


def main():
    data = json.loads((HERE / 'cycle_breakdown_data.json').read_text())
    rows = data['rows']
    assert len(rows) == 8
    assert all(r['total'] == r['hash'] + r['transfer'] + r['remaining'] for r in rows)
    plt.rcParams.update({
        'font.family': 'sans-serif', 'font.sans-serif': ['DejaVu Sans'],
        'font.size': 8, 'axes.labelsize': 9, 'xtick.labelsize': 8,
        'ytick.labelsize': 8, 'legend.fontsize': 8,
        'pdf.fonttype': 42, 'svg.fonttype': 'none',
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.linewidth': 0.7, 'savefig.facecolor': 'white'})
    fig, axes = plt.subplots(1, 2, sharey=True,
                             figsize=(FIGURE_WIDTH_MM / 25.4, FIGURE_HEIGHT_MM / 25.4))
    fig.subplots_adjust(left=0.105, right=0.982, bottom=0.23, top=0.78, wspace=0.15)
    for panel, ax, backend in zip(('a', 'b'), axes, ('shake', 'sha2')):
        selected = [r for r in rows if r['backend'] == backend]
        assert [r['design'] for r in selected] == ['SLotH', 'i', 'c', 't']
        for x, row in enumerate(selected):
            bottom = 0
            for category in ('Hash', 'Transfer', 'Remaining'):
                value = row[category.lower()]
                if value:
                    ax.bar(x, value / 1e6, width=0.62, bottom=bottom / 1e6,
                           color=COLORS[category], edgecolor='none', linewidth=0, zorder=2)
                    if value >= 350_000:
                        ax.text(x, (bottom + value / 2) / 1e6, f'{value / 1e6:.3f}',
                                ha='center', va='center', fontsize=7.5,
                                color='white' if category == 'Hash' else '#25313F')
                    elif category == 'Remaining':
                        # A short remaining segment is too thin for an inset
                        # number; label it beside the bar without hiding it.
                        center = (bottom + value / 2) / 1e6
                        ax.plot([x + 0.31, x + 0.44], [center, center],
                                color='#6D7784', linewidth=0.6, clip_on=False)
                        ax.text(x + 0.48, center, f'{value / 1e6:.3f}',
                                ha='left', va='center', fontsize=6.8, color='#465363')
                bottom += value
            ax.text(x, row['total'] / 1e6 + 0.16, f"{row['total'] / 1e6:.3f}",
                    ha='center', va='bottom', fontsize=8, fontweight='semibold')
        ax.set_xlim(-0.6, 3.9)
        ax.set_ylim(0, 10)
        ax.yaxis.set_major_locator(MultipleLocator(2))
        ax.set_xticks(range(4), ['SLotH', 'i', 'c', 't'])
        ax.tick_params(axis='x', length=0, pad=7)
        ax.tick_params(axis='y', direction='out', length=3)
        ax.set_title(backend.upper(), loc='center', pad=10, fontsize=10, fontweight='semibold')
        ax.annotate(panel, xy=(0, 1), xycoords='axes fraction', xytext=(-18, 10),
                    textcoords='offset points', fontsize=10, fontweight='bold',
                    ha='left', va='baseline', annotation_clip=False)
    axes[0].set_ylabel('Clock cycles (millions)', labelpad=7)
    fig.suptitle('SLH-DSA-128f Sign: clock composition', y=0.974,
                 fontsize=12, fontweight='semibold')
    fig.legend(handles=[Patch(facecolor=COLORS[c], label=c) for c in COLORS],
               loc='upper center', bbox_to_anchor=(0.54, 0.916), ncol=3,
               frameon=False, handlelength=1.3, columnspacing=2.1)
    notes = [
        'Latest adopted i / c; unchanged t. P1U1, matched 33-byte KAT; labels are million cycles.',
        'Transfer = non-overlapped hash-MMIO clocks; i / c / t have no MMIO (Transfer = 0).',
        'Other on-chip work is Remaining. SLotH Hash also includes in-engine setup / chain control.',
        'SHA2: rounds + feed-forward are equal; the 0.211M Hash difference is setup accounting.']
    for y, note in zip((0.125, 0.093, 0.061, 0.029), notes):
        fig.text(0.105, y, note, fontsize=6.8, color='#465363', va='bottom')
    fig.canvas.draw()
    require_matplotlib_panel_alignment(
        fig, json_out=str(HERE / 'qa/clock_breakdown.alignment.json'),
        overlay_svg=str(HERE / 'qa/clock_breakdown.alignment.svg'),
        tolerance_pt=1.5, gutter_tolerance_pt=1.5, require_panel_labels=True, strict=True)
    fig.savefig(HERE / 'clock_breakdown.pdf')
    fig.savefig(HERE / 'clock_breakdown.svg')
    fig.savefig(HERE / 'clock_breakdown.png', dpi=600)
    plt.close(fig)


if __name__ == '__main__':
    main()
