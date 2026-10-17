#!/usr/bin/env python3
"""Check the pinned ABI3 import, without accessing the parent repository.

The sealed source archive is the original db659460 material. Expected production
files are rebuilt only by the documented identifier/path substitutions, source
common partition and module grouping. This is a reproducible source comparison,
not a claim of a separate formal-equivalence proof.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'docs/manifests/experiments/image_chain_import_20261021'
NAMES=('slh_128f','slh_128s','slh_192f','slh_192s','slh_256f','slh_256s')

def digest(data):return hashlib.sha256(data).hexdigest()

def check(run=None):
    receipt=json.loads((ARCHIVE/'SOURCE.json').read_text())
    for path,identity in receipt['reference_evidence'].items():
        assert digest((ARCHIVE/path).read_bytes())==identity['sha256'],('source reference evidence identity',path)
    original=ARCHIVE/'original_source.tar.gz'
    assert digest(original.read_bytes())==receipt['original_archive_sha256'],'original archive identity'
    with tarfile.open(original,'r:gz') as tar:
        source={entry.name:tar.extractfile(entry).read() for entry in tar if entry.isfile()}
    assert {p:digest(v) for p,v in source.items()}==receipt['source_sha256'],'original source identity'
    def text(path):return source[path].decode()
    def mapped(value):
        for old,new in receipt['path_map'].items():value=value.replace(old,new)
        names=receipt['identifier_map']
        return re.sub(r'\b('+'|'.join(names)+r')\b',lambda m:names[m[0]],value)
    expected={}
    for old,new in [('rtl/top/mhbs_micro_processor.sv','rtl/executor/executor.sv'),
        ('rtl/top/mhbs_typed_defs.svh','rtl/executor/instructions.svh'),
        ('rtl/hash_lane/mhbs_keccak.sv','rtl/hash/keccak.sv'),
        ('rtl/memory/mhbs_signature_store.sv','rtl/memory/signature.sv'),
        ('model/micro_isa.py','model/microcode.py'),('model/micro_program.py','model/mHBS.py'),
        ('model/reference/slh_dsa.py','model/reference/slh_dsa.py')]:expected[new]=mapped(text(old))
    expected['rtl/hash/shake-recipe.sv']=mapped(text('rtl/hash_lane/mhbs_single_hash_lane.sv'))+'\n'+mapped(text('rtl/hash_lane/mhbs_single_shake_context.sv'))
    partition={};exec(compile(text('scripts/micro_common_partition.py'),'original_partition','exec'),partition)
    common,top=partition['partition'](text('rtl/top/mhbs_top.sv'))
    expected['rtl/top/common.sv']=mapped(common);expected['rtl/top/top.sv']=mapped(top)
    job=text('model/unified_hbs.py');start=job.index('@dataclass(frozen=True)\nclass Job:');stop=job.index('\n\nclass Machine:',start)
    expected['model/executor.py']=mapped(text('model/micro_vm.py')).replace('\n\n@dataclass\nclass Context:', '\n\n'+job[start:stop]+'\n\n@dataclass\nclass Context:',1)
    expected['model/vectors.py']=mapped(text('tests/slh_fixtures.py')).replace("KAT = Path(__file__).parent / 'kat'","KAT = Path(__file__).resolve().parents[1] / 'tb/kat'")
    profile=mapped(text('model/profiles.py'))
    profile='\n'.join(line for line in profile.split('\n') if not any('Profile("'+name+'"' in line for name in ('xmss_omega2','xmss_omega4','lms_omega2','lms_omega4')))
    expected['model/profiles.py']=profile.replace('ALIASES = {"slh": "slh_128f", "xmss": "xmss_omega4", "lms": "lms_omega4"}','ALIASES = {"slh": "slh_128f"}')
    for path,value in expected.items():assert (ROOT/path).read_bytes()==value.encode(),('unrecorded source change',path)
    sys.path.insert(0,str(ROOT))
    from model.mHBS import compile_micro
    from model.microcode import ABI,MicroImage,sv_definitions
    from model.profiles import SLH_NAMES,get_profile
    assert ABI==3 and set(SLH_NAMES)==set(NAMES)
    assert sv_definitions()==(ROOT/'rtl/executor/instructions.svh').read_text(),'ISA header differs from generator'
    image_checks={}
    for name in NAMES:
        image=compile_micro(name)
        for basename,words in [('program.mem',image.program),('descriptor.mem',image.descriptors)]:
            old=source['manifests/micro/images/'+name+'/'+basename]
            actual=(ROOT/'tb/vectors'/name/basename).read_bytes()
            generated=''.join(f'{word:016x}\n' for word in words).encode()
            assert actual==old==generated,('image differs',name,basename)
            image_checks[name+'/'+basename]=digest(actual)
        for abi in (1,2,4,5):
            descriptor=list(image.descriptors);descriptor[0]=(descriptor[0]&~(31<<27))|(abi<<27)
            try:MicroImage(image.program,tuple(descriptor)).validate()
            except ValueError:pass
            else:raise AssertionError('foreign ABI accepted '+str(abi))
    for name in ('xmss_h10','lms_h10','xmss_omega4','lms_omega4'):
        try:compile_micro(name)
        except ValueError:pass
        else:raise AssertionError('unsupported profile accepted '+name)
    result={'passed':True,'source_commit':receipt['source_commit'],'abi':3,'backend':'shake','configuration':'K1U1',
        'controlled_source_comparisons':{p:digest(value.encode()) for p,value in expected.items()},
        'original_and_regenerated_images':image_checks,'images_equal':12,'foreign_abis_rejected':[1,2,4,5],
        'unsupported_stateful_profiles_rejected':True,'parent_repository_required':False,'formal_equivalence_claimed':False}
    if run:
        candidate=json.loads(Path(run).read_text())['cases']
        baseline=json.loads((ARCHIVE/'source_evidence/functional_rtl.json').read_text())['cases']
        fields=('cycles','hashes','permutations','instructions','hash_trace_sha256','macro_count','macro_hashes','macro_busy_cycles')
        comparisons={}
        for name in NAMES:
            for operation in ('keygen','sign','verify'):
                key=name+'/'+operation;current=candidate[key];old=baseline[key]
                for field in fields:
                    if field in old:assert current[field]==old[field],(key,field,current.get(field),old[field])
                comparisons[key]={field:current[field] for field in fields if field in current}
        extended={}
        for key in sorted(set(candidate)&set(baseline)):
            current,old=candidate[key],baseline[key]
            for field in fields:
                if field in old:assert current[field]==old[field],(key,field,current.get(field),old[field])
            extended[key]={field:current[field] for field in fields if field in current}
        result['rtl_source_baseline_comparisons']=comparisons
        result['all_matching_source_cases']=extended
        result['matching_source_case_count']=len(extended)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--rtl-results',type=Path);p.add_argument('--out',type=Path)
    args=p.parse_args();result=check(args.rtl_results);value=json.dumps(result,indent=2,sort_keys=True)+'\n'
    if args.out:args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(value)
    print(value)

if __name__=='__main__':main()
