"""Constant-space primitive preimage/result multiset fingerprints for RTL checks.

Each item is SHA256(padded primitive input || full primitive output). SHAKE
records its first 49 output bytes; SHA256 records all 32. Count, 256-bit sum
and XOR retain multiplicity without relying on a particular tree traversal.
These probabilistic fingerprints supplement byte-exact final-output checks.
"""
import hashlib
from pathlib import Path


class HashTrace:
    def __init__(self, backend):
        self.backend=backend
        self.hashes=self.blocks=self.sum256=self.xor256=0

    def __call__(self, recipe, data, result):
        if self.backend=='shake':
            padded=bytearray(data+b'\x1f')
            padded.extend(bytes((-len(padded))%136))
            padded[-1]|=0x80
            complete=hashlib.shake_256(data).digest(49)
            blocks=len(padded)//136
        else:
            padded=data+b'\x80'
            padded+=bytes((56-len(padded))%64)+(len(data)*8).to_bytes(8,'big')
            complete=hashlib.sha256(data).digest()
            blocks=len(padded)//64
        assert complete[:len(result)]==result, 'oracle returned an inconsistent primitive digest'
        item=int.from_bytes(hashlib.sha256(padded+complete).digest(),'big')
        self.hashes+=1;self.blocks+=blocks
        self.sum256=(self.sum256+item)% (1<<256)
        self.xor256^=item

    def report(self):
        return dict(hashes=self.hashes,blocks=self.blocks,sum256=f'{self.sum256:064x}',xor256=f'{self.xor256:064x}')


def expected_trace(folder, name, operation, backend):
    """Read frozen fixtures; execute the main VM or independent Verify oracle."""
    from model.executor import Machine,Job
    from model.mHBS import ExternalImage
    from model.profiles import get_profile
    from model.reference import slh_dsa,stateful_shake
    folder=Path(folder);p=get_profile(name,backend)
    def words(filename):return [int(w,16) for w in (folder/filename).read_text().split()]
    cfg=words('job.mem');message=bytes(words('message.mem'))[:cfg[8]] if operation!='keygen' else b''
    seed=[v.to_bytes(32,'little')[:p.n] for v in cfg[:5]]
    job=Job(*seed[:4],identifier=cfg[5].to_bytes(16,'little'),q=cfg[6])
    trace=HashTrace(backend)
    if operation!='verify':
        image=ExternalImage.read(folder).decode(backend)
        machine=Machine(image,job,trace,index_policy='fixed_q_no_guard',recompute_auth=True)
        machine.values[3]=seed[4]
        actual=machine.run(operation=='sign',message)
        expected=bytes(words('expected.mem'))
        if actual!=expected:raise AssertionError('VM bytes differ from independent frozen fixture')
    else:
        nodes=[v.to_bytes(32,'little')[:p.n] for v in words('nodes.mem')]
        if not p.stateful:
            params=getattr(slh_dsa,f'SLH_DSA_{backend.upper()}_{p.n*8}{name[-1].upper()}')
            if not slh_dsa.verify_internal(params,message,b''.join(nodes),job.public+seed[4],trace):
                raise AssertionError('independent SLH Verify rejected frozen fixture')
        else:
            signature=cfg[6].to_bytes(4,'big')
            signature+=(b'' if p.family=='xmss' else p.lmots_typecode.to_bytes(4,'big'))
            signature+=b''.join(nodes[:68])
            signature+=(b'' if p.family=='xmss' else p.typecode.to_bytes(4,'big'))+b''.join(nodes[68:])
            if not stateful_shake.verify(name,message,signature,job.public,seed[4],job.identifier,
                                         hash_backend=backend,observe_hash=trace):
                raise AssertionError('independent stateful Verify rejected frozen fixture')
    return trace.report()
