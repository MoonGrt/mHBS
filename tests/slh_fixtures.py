"""SLH KAT inputs and hash trace observations shared by current validation."""
import hashlib
import json
from pathlib import Path
from model.profiles import get_profile
from model.unified_hbs import Job

KAT = Path(__file__).parent / 'kat'


def default_job(name):
    profile = get_profile(name)
    if profile.family != 'slh':
        raise ValueError('Only SLH profiles are supported by current fixtures')
    vector = json.loads(next(KAT.glob(f'slh_dsa_shake_{profile.n*8}f_siggen_acvp_tc*.json')).read_text())
    secret_key, n = bytes.fromhex(vector['sk']), profile.n
    return Job(secret_key[:n], secret_key[n:2*n], secret_key[2*n:3*n], secret_key[2*n:3*n]), bytes.fromhex(vector['message'])


class Observation:
    def __init__(self,n):
        self.n=n;self.counts=[0,0];self.trace=hashlib.sha256();self.nodes={}
    def __call__(self,kind,data,result):
        self.counts[0]+=1;self.counts[1]+=len(data)//136+1
        self.trace.update(len(data).to_bytes(4,'little')+data+result)
        # Addressed Merkle/FORS nodes have domain 2/3 and a full 32-byte ADRS.
        n=self.n
        if len(data) in (2*n+32,3*n+32):
            adr=data[n:n+32];domain=int.from_bytes(adr[16:20],'big')
            if domain in (2,3):self.nodes[adr.hex()]=result.hex()
    def record(self):
        return dict(counts=self.counts,hash_trace_sha256=self.trace.hexdigest(),
                    nodes=len(self.nodes),nodes_sha256=hashlib.sha256(json.dumps(self.nodes,sort_keys=True).encode()).hexdigest())
