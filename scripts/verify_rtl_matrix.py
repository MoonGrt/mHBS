#!/usr/bin/env python3
"""Run the declared seven-profile verification matrix through Make."""
import subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model.profiles import PROFILES

def matrix():
    for name,p in PROFILES.items():
        yield name,p.lanes,0,0,5
        yield name,p.lanes,1,1,5
        yield name,1 if p.family=='slh' else 2,0 if p.family=='slh' else 1,1,5
        if p.stateful:
            yield name,1,0,1,0
            yield name,1,0,1,1023

if __name__=='__main__':
    for name,lanes,swap,bp,q in matrix():
        subprocess.run(['make','rtl-profile-test',f'PROFILE={name}',f'LANES={lanes}',f'SWAP={swap}',f'BACKPRESSURE={bp}',f'Q={q}'],cwd=ROOT,check=True)
