#!/usr/bin/env python3
"""Archive a measured candidate without overwriting prior evidence."""
import argparse,json,shutil
from autonomous_flow import ROOT,BASE,BUILD,sha,write

def main():
    p=argparse.ArgumentParser();p.add_argument('tag');args=p.parse_args()
    source=BUILD/args.tag;target=BASE/'candidates'/args.tag
    data=json.loads((source/'ppa.json').read_text())
    inputs=json.loads((source/'inputs.json').read_text())
    assert sha(source/'source_snapshot.tar.gz')==inputs['snapshot_sha256']
    names=['inputs.json','source_snapshot.tar.gz','ppa.json','utilization.rpt',
        'utilization_hierarchical.rpt','timing_summary.rpt','post_synth.dcp','rom_cells.tsv']
    names += [n for n in ('synth_seconds.txt','synthesis.json','route_flow.tcl','route_status.rpt','check_timing.rpt',
        'final_clock.json','post_route_final_clock.dcp','constraints.xdc','post_place.dcp',
        'post_place_timing.rpt','route_resume.json','route_seconds.txt','driver.log','input_routed.dcp') if (source/n).exists()]
    if (source/'frozen').is_dir():
        names += [str(p.relative_to(source)) for p in sorted((source/'frozen').rglob('*')) if p.is_file()]
    for n in names:
        assert (source/n).is_file(),n
        if (target/n).exists():assert sha(target/n)==sha(source/n),'refuse overwrite '+n
    target.mkdir(parents=True,exist_ok=True)
    for n in names:
        if not (target/n).exists():
            (target/n).parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source/n,target/n)
    write(target/'evidence.json',dict(version='v4.1',tag=args.tag,index_policy=data.get('index_policy','guarded'),
        stage=data['stage'],evidence_sha256={n:sha(target/n) for n in names}))
    print('CANDIDATE_ARCHIVED',args.tag)

if __name__=='__main__':main()
