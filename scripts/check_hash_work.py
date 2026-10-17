#!/usr/bin/env python3
"""Compare every ABI 2 Hash input/result with the independent SLH reference.

The comparison includes multiplicity and is insensitive to task scheduling.
Task identities use SHA256(u32le(input length)||input||u32le(result length)||result),
without trusting recipe IDs or reference function names. Sorted binary chunks
bound Python memory, including the largest small-signature profiles. The
receipt retains compact sorted-work digests; temporary task files are removed.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import heapq
import json
from pathlib import Path
import struct
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.microcode import MicroImage
from model.mHBS import compile_micro
from model.executor import MicroMachine
from model.profiles import SLH_NAMES,get_profile
from model.reference import slh_dsa
from model.vectors import KAT,default_job

FORMAT='hbs_hash_work_v1'
FINGERPRINT='SHA256(u32le(input length)||input||u32le(result length)||result)'
SOURCE_PATHS=('scripts/check_hash_work.py','model/microcode.py',
    'model/mHBS.py','model/executor.py','model/profiles.py',
    'model/reference/slh_dsa.py','model/vectors.py')


def sha_bytes(data): return hashlib.sha256(data).hexdigest()
def sha_file(path): return sha_bytes(Path(path).read_bytes())


def fingerprint(data,result):
    h=hashlib.sha256();h.update(struct.pack('<I',len(data)));h.update(data)
    h.update(struct.pack('<I',len(result)));h.update(result)
    return h.digest()


class HashWork:
    def __init__(self,folder,*,chunk_size=262144):
        if chunk_size<1: raise ValueError('chunk size')
        self.folder=Path(folder);self.folder.mkdir(parents=True)
        self.chunk_size=chunk_size;self.buffer=[];self.chunks=[]
        self.tasks=0;self.permutations=0;self.ordered=hashlib.sha256();self.finished=False

    def __call__(self,_kind,data,result):
        if self.finished: raise ValueError('finished Hash observer')
        key=fingerprint(data,result);self.buffer.append(key);self.ordered.update(key)
        self.tasks+=1;self.permutations+=len(data)//136+1
        if len(self.buffer)>=self.chunk_size: self._flush()

    def _flush(self):
        if not self.buffer: return
        self.buffer.sort();path=self.folder/f'{len(self.chunks):04d}.bin'
        path.write_bytes(b''.join(self.buffer));self.chunks.append(path);self.buffer.clear()

    def finish(self):
        self._flush();self.finished=True
        return self

    @staticmethod
    def _records(path):
        with path.open('rb') as source:
            while block:=source.read(32*32768):
                if len(block)%32: raise ValueError('truncated Hash task chunk')
                for offset in range(0,len(block),32): yield block[offset:offset+32]

    def sorted_records(self):
        if not self.finished: raise ValueError('unfinished Hash observer')
        return heapq.merge(*(self._records(path) for path in self.chunks))


def compare_work(reference,candidate):
    """External merge, counting repeated tasks rather than comparing sets."""
    reference.finish();candidate.finish()
    left=iter(reference.sorted_records());right=iter(candidate.sorted_records())
    a=next(left,None);b=next(right,None)
    ref_digest=hashlib.sha256();candidate_digest=hashlib.sha256()
    matched=ref_extra=candidate_extra=0
    while a is not None or b is not None:
        if b is None or a is not None and a<b:
            ref_digest.update(a);ref_extra+=1;a=next(left,None)
        elif a is None or b<a:
            candidate_digest.update(b);candidate_extra+=1;b=next(right,None)
        else:
            ref_digest.update(a);candidate_digest.update(b);matched+=1
            a=next(left,None);b=next(right,None)
    same=not ref_extra and not candidate_extra
    return dict(reference_tasks=reference.tasks,candidate_tasks=candidate.tasks,
        reference_permutations=reference.permutations,candidate_permutations=candidate.permutations,
        matched_tasks=matched,reference_extra=ref_extra,candidate_extra=candidate_extra,
        reference_multiset_sha256=ref_digest.hexdigest(),candidate_multiset_sha256=candidate_digest.hexdigest(),
        reference_order_sha256=reference.ordered.hexdigest(),candidate_order_sha256=candidate.ordered.hexdigest(),
        tasksetsame=same,relation='exact_multiset' if same else 'different_multiset')


def source_identity(names):
    paths=set(SOURCE_PATHS)
    for name in names:
        p=get_profile(name)
        path=next(KAT.glob(f'slh_dsa_shake_{p.n*8}f_siggen_acvp_tc*.json'))
        paths.add(str(path.relative_to(ROOT)))
    return {path:sha_file(ROOT/path) for path in sorted(paths)}


def check_profile(name,folder,image_root,chunk_size):
    p=get_profile(name);job,message=default_job(name)
    params=getattr(slh_dsa,f'SLH_DSA_SHAKE_{p.n*8}{name[-1].upper()}')
    image_path=Path(image_root)/name;image=MicroImage.read(image_path)
    if image!=compile_micro(name): raise ValueError('image does not match current compiler')
    folder=Path(folder);rows={};sk=pk=signature=None;log=[]
    image_hashes={key:sha_file(image_path/(key+'.mem')) for key in ('program','descriptor')}
    for operation,label in enumerate(('keygen','sign','verify')):
        start=time.monotonic()
        with tempfile.TemporaryDirectory(prefix=f'.{name}_{label}_',dir=folder) as tmp:
            reference=HashWork(Path(tmp)/'reference',chunk_size=chunk_size)
            candidate=HashWork(Path(tmp)/'candidate',chunk_size=chunk_size)
            if operation==0:
                sk,pk=slh_dsa.keygen_internal(params,job.secret,job.prf,job.public,reference)
                expected=sk+pk
            elif operation==1:
                signature=slh_dsa.sign_internal(params,message,sk,job.random,reference);expected=signature
            else:
                if not slh_dsa.verify_internal(params,message,signature,pk,reference):
                    raise AssertionError('reference Verify failed')
                expected=True
            root=pk[p.n:] if operation else bytes(p.n)
            msg=message if operation else b'';sig=signature if operation==2 else b''
            machine=MicroMachine(image,job,root,msg,operation,sig,observe=candidate,
                instruction_limit=2_000_000_000)
            actual=machine.run()
            if actual!=expected: raise AssertionError((name,label,'full output mismatch'))
            comparison=compare_work(reference,candidate)
            passed=comparison['tasksetsame'] and comparison['reference_permutations']==comparison['candidate_permutations']
            row=dict(passed=passed,profile=name,operation=operation,instructions=machine.instructions,
                instruction_words=image.used,output_sha256=sha_bytes(b'' if operation==2 else actual),
                verify_pass=bool(actual) if operation==2 else None,
                inputs_sha256=dict(image_hashes,
                    secret=sha_bytes(job.secret),prf=sha_bytes(job.prf),public=sha_bytes(job.public),
                    random=sha_bytes(job.random),root=sha_bytes(root),message=sha_bytes(msg),signature=sha_bytes(sig)),
                seconds=time.monotonic()-start,**comparison)
            rows[f'{name}/{label}']=row
            marker='HASH_WORK_PASS' if passed else 'HASH_WORK_FAIL'
            log.append(f'{marker} {name} {label} reference={reference.tasks} candidate={candidate.tasks} '
                f'matched={comparison["matched_tasks"]} reference_extra={comparison["reference_extra"]} '
                f'candidate_extra={comparison["candidate_extra"]} digest={comparison["candidate_multiset_sha256"]}')
            print(log[-1],flush=True)
            if not passed:
                (folder/f'{name}.log').write_text('\n'.join(log)+'\n')
                raise AssertionError((name,label,'Hash work multiset mismatch',comparison))
    (folder/f'{name}.log').write_text('\n'.join(log)+'\n')
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=('all',*SLH_NAMES),default='all')
    parser.add_argument('--out',type=Path,default=Path('build/image-chain-tree/typed_final/hash_work'))
    parser.add_argument('--image-root',type=Path,default=Path('tb/vectors'))
    parser.add_argument('--jobs',type=int,default=3)
    parser.add_argument('--chunk-size',type=int,default=262144)
    args=parser.parse_args();names=SLH_NAMES if args.profile=='all' else (args.profile,)
    if args.jobs<1 or args.chunk_size<1: parser.error('positive jobs/chunk size required')
    folder=args.out.resolve();folder.mkdir(parents=True,exist_ok=True)
    identity=source_identity(names);start=time.monotonic();cases={}
    image_root=args.image_root.resolve()
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures=[pool.submit(check_profile,name,folder,image_root,args.chunk_size) for name in names]
        for future in concurrent.futures.as_completed(futures): cases.update(future.result())
    if source_identity(names)!=identity: raise ValueError('Hash work sources changed during gate')
    result=dict(passed=len(cases)==len(names)*3 and all(row['passed'] for row in cases.values()),
        format=FORMAT,fingerprint=FINGERPRINT,source_sha256=identity,cases=cases,
        sorted_record_bytes=32,chunk_tasks=args.chunk_size,
        logs={path.name:sha_file(path) for path in sorted(folder.glob('*.log'))},
        seconds=time.monotonic()-start)
    (folder/'results.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print('HASH_WORK_ALL_PASS',len(cases),'cases',folder,flush=True)


if __name__=='__main__':main()
