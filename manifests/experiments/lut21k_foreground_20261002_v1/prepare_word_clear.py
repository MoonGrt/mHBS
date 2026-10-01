import json,tarfile,shutil,difflib,hashlib
from pathlib import Path
root=Path.cwd();r=root/'manifests/experiments/lut21k_foreground_20261002_v1';base=Path('manifests/experiments/unified_hbs_v4.2/external_job_message');tag='lut21k_20261002_v1_word_clear';w=root/'build/v4.2/lut21k_workspaces'/tag;w.mkdir(exist_ok=False)
with tarfile.open(root/base/'candidates/lut21k_20261002_v1_bank/source_snapshot.tar.gz') as t:t.extractall(w,filter='data')
p=w/base/'candidates/parent_right_20260930_v1';p.mkdir(parents=True);shutil.copy2(root/base/'candidates/parent_right_20260930_v1/simulation.json',p/'simulation.json')
rel='rtl/hash_lane/mhbs_compact_shake_context_lane.sv';p=w/rel;s=p.read_text();s=s.replace("wire [63:0] round_or_clear=clear_stream ? 64'd0\n            : advanced_state[word_index*64 +:64];",'''wire clear_word=clear_stream && !select_stream && !take_fast && !take_feedback;
        wire [63:0] round_or_clear=advanced_state[word_index*64 +:64];''');s=s.replace('''        always_ff @(posedge clk)
            if(!rst && (lane_state==RUN || take_fast || select_stream || clear_stream))
                sponge_state[word_index*64 +:64]<=next_word;''','''        // Preserve reset-as-hold, but expose first-block clearing as a
        // synchronous register clear instead of a wide input-data mask.
        always_ff @(posedge clk)
            if(!rst) begin
                if(clear_word) sponge_state[word_index*64 +:64]<=64'd0;
                else if(lane_state==RUN || take_fast || select_stream || clear_stream)
                    sponge_state[word_index*64 +:64]<=next_word;
            end''');assert s!=p.read_text();p.write_text(s)
f=w/'experiments/v4.2/lut21k/reference/shake.sv';f.parent.mkdir(parents=True,exist_ok=True);f.write_text((root/rel).read_text().replace('module mhbs_compact_shake_context_lane #','module mhbs_compact_shake_context_lane_ref #'))
c=dict(label='word_clear',tag=tag,workspace=str(w),baseline='lut21k_20261002_v1_bank',code_sha256={str(p.relative_to(w)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ['rtl','tb','scripts','experiments','model','tests'] for p in (w/d).rglob('*') if p.is_file()});out=r/'candidates'/tag;out.mkdir(parents=True);(out/'candidate.json').write_text(json.dumps(c,indent=2)+'\n');(out/'incremental.patch').write_text(''.join(difflib.unified_diff((root/rel).read_text().splitlines(True),s.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel)));cfg=json.loads((r/'config.json').read_text());cfg['candidates'].append(c);(r/'config.json').write_text(json.dumps(cfg,indent=2)+'\n');shutil.copy2('/tmp/prepare_word_clear.py',r/'prepare_word_clear.py');print(w)
