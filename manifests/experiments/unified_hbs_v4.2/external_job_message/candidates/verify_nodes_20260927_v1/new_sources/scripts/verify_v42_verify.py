#!/usr/bin/env python3
"""Verify externally supplied SLH nodes using the unchanged signing images."""
import argparse, concurrent.futures, hashlib, json, re
from pathlib import Path
from v42_external_flow import ROOT,BASE,NAMES,PARAMS,rtl,run,sha,write,capture
from v42_common_partition import partition
from model.reference import slh_dsa


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag');parser.add_argument('--quick',action='store_true')
    args=parser.parse_args();folder=capture(args.tag);out=folder/'verify';out.mkdir(exist_ok=True)
    def profile(name):
        source=BASE/'vectors'/name/'sign';cfg=json.loads((source/'job.json').read_text())
        n=len(bytes.fromhex(cfg['public_seed']));params=getattr(slh_dsa,f'SLH_DSA_SHAKE_{n*8}F')
        sig=bytes(int(x,16) for x in (source/'expected.mem').read_text().split())
        msg=bytes(int(x,16) for x in (source/'message.mem').read_text().split())[:cfg['message_bytes']]
        pk=bytes.fromhex(cfg['public_seed']+cfg['public_root']);assert slh_dsa.verify_internal(params,msg,sig,pk)
        vec=out/name;vec.mkdir(exist_ok=True)
        (vec/'nodes.mem').write_text(''.join(f'{int.from_bytes(sig[i:i+n],"little"):064x}\n' for i in range(0,len(sig),n)))
        (vec/'message.mem').write_text(''.join(f'{x:02x}\n' for x in msg))
        cfgpath=vec/'config.json';write(cfgpath,dict(profile=name,node_bytes=n,nodes=len(sig)//n,message_bytes=len(msg),public_seed=cfg['public_seed'],public_root=cfg['public_root'],source_signature_sha256=sha(source/'expected.mem')))
        binaries={}
        def binary(swap=0,stats=True,part=False,bad_root=False):
            key=f's{swap}_p{int(stats)}_c{int(part)}_r{int(bad_root)}'
            if key in binaries:return binaries[key]
            d=vec/key;d.mkdir(exist_ok=True);sources=rtl();defines=[]
            if part:
                common,shell=partition((ROOT/'rtl/top/mhbs_top.sv').read_text());(d/'common.sv').write_text(common);(d/'top.sv').write_text(shell)
                sources=[x for x in sources if x!='rtl/top/mhbs_top.sv']+[str(d/'common.sv'),str(d/'top.sv')];defines=['-DMHBS_PARTITIONED']
            root=int.from_bytes(bytes.fromhex(cfg['public_root']),'little')^int(bad_root)
            options=[f"-GPUBLIC_SEED=256'h{int.from_bytes(bytes.fromhex(cfg['public_seed']),'little'):064x}",f"-GPUBLIC_ROOT=256'h{root:064x}",f'-GMESSAGE_BYTES={len(msg)}',f'-GNODE_BYTES={n}',f'-GNODES={len(sig)//n}',f'-GSWAP={swap}',f'-GPROFILE_ENABLE={int(stats)}']
            exe=d/'obj/Vtb_mhbs_verify'
            run(['verilator','--binary','--timing','-O3','-j','8','-Wno-fatal','-Wno-WIDTH','-Wno-UNOPTFLAT',*defines,'--top-module','tb_mhbs_verify',*options,'--Mdir',str(exe.parent),*sources,'tb/integration/tb_mhbs_verify.sv'],d/'compile.log')
            binaries[key]=exe;return exe
        cases={}
        def case(label,opts=(),swap=0,stats=True,part=False,bad_root=False):
            exe=binary(swap,stats,part,bad_root);log=vec/(label+'.log')
            run([str(exe),'+IMAGE='+str(BASE/'images'/name),'+VECTOR='+str(vec),*opts],log)
            if label=='fault':assert 'VERIFY_FAULT_PASS' in log.read_text();row=dict(passed=True)
            else:
                hits=re.findall(r'VERIFY_PASS accepted=(\d+) nodes=(\d+) cycles=(\d+) waits=(\d+) hashes=(\d+) permutations=(\d+) zero=(\d+) full=(\d+)',log.read_text());assert hits,label
                row=dict(zip(('accepted','nodes','cycles','waits','hashes','permutations','zero','full'),map(int,hits[-1])));row['passed']=True
            row['log_sha256']=sha(log);cases[label]=row
            return row
        reference=case('normal');assert reference['zero'] and reference['full']
        if not args.quick:
            tests=[('randomizer',0),('fors_secret',1),('fors_auth',2),('wots',1+params.k*(params.a+1)),('xmss_auth',1+params.k*(params.a+1)+params.wots_len),('last_auth',len(sig)//n-1)]
            for label,index in tests:
                changed=bytearray(sig);changed[index*n]^=1;assert not slh_dsa.verify_internal(params,msg,changed,pk)
                case(label,(f'+FLIP={index}','+EXPECT=0'))
            changed=bytes([msg[0]^1])+msg[1:];assert not slh_dsa.verify_internal(params,changed,sig,pk)
            case('message',('+BAD_MESSAGE=1','+EXPECT=0'))
            assert not slh_dsa.verify_internal(params,msg,sig,pk[:-n]+bytes([pk[-n]^1])+pk[-n+1:])
            case('root',('+EXPECT=0',),bad_root=True)
            for label,opts,kw in [('stall',('+STALL=1',),{}),('reset_replay',('+ABORT_AT=4','+REPLAY=1'),{}),('truncated_wait_reset',('+CUT=5',),{}),('swap',(),dict(swap=1)),('no_profile',(),dict(stats=False)),('partition',(),dict(part=True))]:
                row=case(label,opts,**kw)
                for field in ('hashes','permutations','nodes'):assert row[field]==reference[field],(label,field)
                assert row['cycles']-row['waits']==reference['cycles'],label
            case('fault',('+FAULT=1',))
        write(vec/'results.json',dict(passed=True,cases=cases));print('VERIFY_PROFILE_PASS',name,len(cases),'cases',flush=True)
        return name,cases
    with concurrent.futures.ThreadPoolExecutor(3) as pool:results=dict(pool.map(profile,NAMES))
    write(out/'results.json',dict(passed=True,quick=args.quick,source_snapshot_sha256=sha(folder/'source_snapshot.tar.gz'),profiles=results))
    print('VERIFY_RTL_PASS',sum(map(len,results.values())),'cases',flush=True)
if __name__=='__main__':main()
