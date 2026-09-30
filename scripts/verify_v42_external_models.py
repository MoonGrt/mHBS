#!/usr/bin/env python3
"""Software-first gate for layout 3 and independent inputs."""
import hashlib,json,sys
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model.slh64 import CompactImage,CompactMachine,pack
from model.profiles import SLH_NAMES
from model.slh64_external import ExternalImage,ExternalMachine,compile_external,convert_legacy
from model.reference import slh_dsa
from tests.slh_fixtures import default_job,KAT
from tests.slh_fixtures import Observation
BASE=ROOT/'manifests/experiments/unified_hbs_v4.2/external_job_message'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2)+'\n')
records={};negative=[]
for name in SLH_NAMES:
    image=compile_external(name);image.write(BASE/'images'/name)
    job,msg=default_job(name);n=len(job.secret);params=getattr(slh_dsa,f'SLH_DSA_SHAKE_{n*8}{name[-1].upper()}')
    sk,pk=slh_dsa.keygen_internal(params,job.secret,job.prf,job.public);root=pk[n:]
    kat=json.loads(next(KAT.glob(f'slh_dsa_shake_{n*8}f_siggen_acvp_tc*.json')).read_text())
    if name.endswith('f'):assert sk+pk==bytes.fromhex(kat['sk']+kat['pk'])
    for sign in (False,True):
        op='sign' if sign else 'keygen';message=msg if sign else b'';supplied_root=root if sign else bytes(n)
        old=CompactImage.read(ROOT/'manifests/experiments/unified_hbs_v4.2/images'/name/op) if name.endswith('f') else pack(name,job,message,supplied_root,sign)
        converted,j,r,m,s=convert_legacy(old);assert converted==image
        assert image.decode().words(sign)==old.decode()[0].words(sign)
        obs=Observation(n);legacy_obs=Observation(n)
        machine=ExternalMachine(image,job,supplied_root,message,sign,obs);actual=machine.run()
        expected=CompactMachine(old,legacy_obs).run();assert actual==expected and obs.record()==legacy_obs.record()
        ref=slh_dsa.sign_internal(params,message,sk) if sign else sk+pk
        assert actual==ref
        if sign:
            assert slh_dsa.verify_internal(params,message,actual,pk)
            if name.endswith('f'):assert hashlib.sha256(actual).hexdigest()==kat['signature_sha256']
        try:machine.run()
        except ValueError:pass
        else:raise AssertionError('repeat operation')
        folder=BASE/'vectors'/name/op;folder.mkdir(parents=True,exist_ok=True)
        (folder/'expected.mem').write_text(''.join(f'{x:02x}\n' for x in actual))
        (folder/'message.mem').write_text(''.join(f'{x:02x}\n' for x in (message or b'\0')))
        (folder/'metadata.mem').write_text(''.join(f'{x:08x}\n' for x in (len(actual),*obs.counts,int(sign),n,len(message))))
        cfg=dict(profile=name,operation=int(sign),message_bytes=len(message),secret_seed=job.secret.hex(),secret_prf=job.prf.hex(),public_seed=job.public.hex(),randomizer=job.random.hex(),public_root=supplied_root.hex())
        write(folder/'job.json',cfg)
        records[name+'/'+op]=dict(**obs.record(),output_sha256=hashlib.sha256(actual).hexdigest(),files={p.name:sha(p) for p in folder.iterdir()})
        print('EXTERNAL_MODEL_PASS',name,op,flush=True)
    for label,words in [('entry',list(image.descriptors)),('reserved',list(image.descriptors))]:
        words[0]^=1<<(36 if label=='entry' else 46)
        try:replace(image,descriptors=tuple(words)).decode()
        except ValueError:negative.append(name+'/'+label)
        else:raise AssertionError(label)
    for label,invalid in (
        ('program_capacity',replace(image,program=image.program+(0,))),
        ('keygen_entry16',replace(image,descriptors=(image.descriptors[0]|(1<<40),)+image.descriptors[1:])),
        ('sign_entry16',replace(image,descriptors=(image.descriptors[0]|(1<<45),)+image.descriptors[1:])),
    ):
        try:invalid.decode()
        except ValueError:negative.append(name+'/'+label)
        else:raise AssertionError(label)
    words=list(old.program);words[16]=1
    try:convert_legacy(replace(old,program=tuple(words)))
    except ValueError as e:
        assert '16-word capacity' in str(e)
        negative.append(name+'/legacy_program_overflow')
    else:raise AssertionError('legacy program silently truncated')
    for sign,message in [(True,b''),(True,bytes(88)),(False,b'x')]:
        try:ExternalMachine(image,job,root,message,sign)
        except ValueError:negative.append(name+'/length/'+str(len(message)))
        else:raise AssertionError('invalid length')
write(BASE/'software_gate.json',dict(passed=True,layout_revision=3,profiles=records,rejected_cases=negative,source_sha256={str(p.relative_to(ROOT)):sha(p) for p in [*ROOT.glob('model/**/*.py'),Path(__file__),ROOT/'tests/slh_fixtures.py']}))
print('EXTERNAL_SOFTWARE_GATE_PASS',len(records),flush=True)
