"""Generate all images and vectors from algorithms, without existing vectors."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile

from model.profiles import PROFILES, ALIASES, get_profile, profile_names
from model.hashes import block_count
from model.executor import Job, Machine, compile_image
from model.stateful import cold_image
from model.mHBS import compile_image as compile_hardware_image
from model.reference import slh_dsa, stateful_shake

ROOT = Path(__file__).resolve().parents[1]
MEM_FILES = ('program.mem', 'template.mem', 'descriptor.mem', 'job.mem',
             'message.mem', 'nodes.mem', 'expected.mem', 'meta.mem')


def mem(path: Path, values, width: int) -> None:
    path.write_text(''.join(f'{int(value):0{width}x}\n' for value in values))


def generate_profile(name: str, config: dict, output: str, hash_backend="shake") -> dict:
    profile = get_profile(name, hash_backend)
    name = profile.name
    def octets(key, length):
        value = bytes.fromhex(config[key])
        if len(value) != length:
            raise ValueError(f'{name}: {key} must be {length} bytes')
        return value
    job = Job(*(octets(k, profile.n) for k in
                ('secret_seed', 'secret_prf', 'public_seed', 'randomizer')),
              identifier=octets('identifier', 16), q=config['q'])
    message = bytes.fromhex(config['message'])
    if not (0 if profile.stateful else 1) <= len(message) <= 87:
        raise ValueError(f'{name}: invalid message length for selected family')
    if type(job.q) is not int or not (0 <= job.q < (1 << profile.h) if profile.stateful else job.q == 0):
        raise ValueError(f'{name}: q outside selected tree')
    if not profile.stateful and (job.q != 0 or any(job.identifier)):
        raise ValueError(f'{name}: SLH requires q=0 and zero identifier')
    if profile.stateful:
        from model.reference.stateful_native import generate
        keygen, signature, native_counts = generate(name, job, message, hash_backend)
        root = keygen[4:36] if profile.family == 'xmss' else keygen[24:56]
        operation_counts = [native_counts[:2], native_counts[2:]]
    else:
        image = compile_image(name, hash_backend=hash_backend)
        kg = Machine(image, job, index_policy='fixed_q_no_guard')
        keygen = kg.run(False)
        root = kg.values[3][:profile.n]
        signing = Machine(image, job, index_policy='fixed_q_no_guard')
        signing.values[3] = root
        signature = signing.run(True, message)
        operation_counts = [[kg.hashes,kg.permutations],[signing.hashes,signing.permutations]]
    verify_counts = [0, 0]
    if profile.family == 'slh':
        params = getattr(slh_dsa, f'SLH_DSA_{hash_backend.upper()}_{profile.n*8}{name[-1].upper()}')
        def observe(kind, data, result):
            verify_counts[0] += 1
            verify_counts[1] += block_count(len(data), hash_backend)
        if not slh_dsa.verify_internal(params, message, signature,
                                       job.public + root, observe):
            raise AssertionError(f'{name}: independent SLH verifier rejected signature')
        nodes = [signature[i:i+profile.n] for i in range(0, len(signature), profile.n)]
    else:
        observed = {}
        if not stateful_shake.verify(name, message, signature, job.public,
                                     root, job.identifier, observed, hash_backend):
            raise AssertionError(f'{name}: independent stateful verifier rejected signature')
        verify_counts = [observed['hashes'], observed['permutations']]
        q, random, chains, auth = stateful_shake.parse_signature(name, signature, hash_backend)
        assert q == job.q
        nodes = [random, *chains, *auth]
    external = compile_hardware_image(name, hash_backend=hash_backend)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    records = []
    # Write only after all model/independent-verifier checks succeeded. Each
    # operation is staged so interrupted calculations leave old vectors intact.
    with tempfile.TemporaryDirectory(prefix=f'.{name}_', dir=output) as temporary:
        staging = Path(temporary)
        for op, label in enumerate(('keygen', 'sign', 'verify')):
            folder = staging/label
            external.write(folder)
            data = (keygen, signature, b'')[op]
            counts = (*operation_counts, verify_counts)[op]
            # Preserve the original fixed-vector convention: stateful Keygen
            # retains unused message/root/node fields; the harness masks them.
            payload = message if op or profile.stateful else b''
            supplied_root = root if op or profile.stateful else bytes(profile.n)
            supplied_nodes = nodes if op == 2 or profile.stateful else [bytes(profile.n)]
            cfg = [int.from_bytes(x, 'little') for x in
                   (job.secret, job.prf, job.public, job.random, supplied_root, job.identifier)]
            cfg += [job.q, op, len(payload)]
            mem(folder/'job.mem', cfg, 64)
            mem(folder/'message.mem', payload + bytes(87-len(payload)), 2)
            mem(folder/'nodes.mem', (int.from_bytes(x, 'little') for x in supplied_nodes), 64)
            mem(folder/'expected.mem', data or b'\0', 2)
            mem(folder/'meta.mem', [len(data), *counts, len(supplied_nodes), int(op == 2)], 16)
            destination = output/name/label
            destination.mkdir(parents=True, exist_ok=True)
            for filename in MEM_FILES:
                (folder/filename).replace(destination/filename)
            records.append(dict(operation=label,output_bytes=len(data),
                                hashes=counts[0],permutations=counts[1],
                                sha256={n:hashlib.sha256((destination/n).read_bytes()).hexdigest()
                                        for n in MEM_FILES}))
    return dict(profile=name,hash_backend=hash_backend,q=job.q,message_hex=message.hex(),
                public_root=root.hex(),independent_verify_passed=True,
                sign_recompute_auth=profile.stateful,operations=records)


def generate_verify_profile(name: str, config: dict, output: str, hash_backend="shake") -> dict:
    """Build a real-height Verify Job without generating a complete tree.

    Independent WOTS/LMOTS equations form one leaf. Deterministic synthetic
    siblings form an authentication path of exactly h levels and its root.
    This checks Verify/address semantics; it is not a complete-tree keygen.
    No project VM, recipe descriptor or native complete-tree signer is called.
    """
    from model.reference.stateful_shake import H, be, masked, digits
    p = get_profile(name, hash_backend)
    if not p.stateful:
        raise ValueError('Verify-only synthetic paths require XMSS or LMS')
    job = Job(*(bytes.fromhex(config[k]) for k in
                ('secret_seed', 'secret_prf', 'public_seed', 'randomizer')),
              identifier=bytes.fromhex(config['identifier']), q=config['q'])
    if any(len(v) != 32 for v in (job.secret, job.prf, job.public, job.random)) or len(job.identifier) != 16:
        raise ValueError('invalid seed, randomizer or identifier length')
    if type(job.q) is not int or not 0 <= job.q < 1 << p.h:
        raise ValueError('q outside selected tree')
    message = bytes.fromhex(config['message'])
    if not 0 <= len(message) <= 87:
        raise ValueError('stateful message length must be 0..87')
    h = lambda data: H(data, hash_backend)
    xmss = p.family == 'xmss'
    q = job.q
    auth = tuple(hashlib.sha256(b'mHBS main template Verify sibling\0' +
                 name.encode() + hash_backend.encode() + be(q) + be(level)).digest()
                 for level in range(p.h))
    secrets, endpoints = [], []
    # Keep one leaf's chain history for signing after the synthetic root is known.
    histories = []
    for i in range(67):
        value = h(be(4,32) + job.secret + job.public + bytes(16) +
                  be(q) + be(i) + bytes(8)) if xmss else h(
                  job.identifier + be(q) + be(i,2) + b'\xff' + job.secret)
        secrets.append(value)
        history = [value]
        for step in range(15):
            value = masked(job.public,0,q,i,step,value,hash_backend=hash_backend) if xmss else h(
                    job.identifier + be(q) + be(i,2) + be(step,1) + value)
            history.append(value)
        histories.append(history)
        endpoints.append(value)
    if xmss:
        level = 0
        while len(endpoints) > 1:
            following = [masked(job.public,1,q,level,i//2,endpoints[i],endpoints[i+1],
                                hash_backend=hash_backend) for i in range(0,len(endpoints)-1,2)]
            endpoints = following + (endpoints[-1:] if len(endpoints)&1 else [])
            level += 1
        node = endpoints[0]
    else:
        node = h(job.identifier + be(q) + b'\x80\x80' + b''.join(endpoints))
        node = h(job.identifier + be((1 << p.h) + q) + b'\x82\x82' + node)
    for level, sibling in enumerate(auth):
        left, right = (sibling,node) if q >> level & 1 else (node,sibling)
        node = masked(job.public,2,0,level,q >> (level+1),left,right,
                      hash_backend=hash_backend) if xmss else h(
                      job.identifier + be(((1 << p.h)+q) >> (level+1)) + b'\x83\x83' + left + right)
    root = node
    random = h(be(3,32) + job.prf + be(q,32)) if xmss else job.random
    digest = h(be(2,32) + random + root + be(q,32) + message) if xmss else h(
               job.identifier + be(q) + b'\x81\x81' + random + message)
    chains = tuple(histories[i][digit] for i,digit in enumerate(digits(digest,4)))
    signature = be(q) + (b'' if xmss else be(p.lmots_typecode)) + random + b''.join(chains)
    signature += (b'' if xmss else be(p.typecode)) + b''.join(auth)
    public = be(p.typecode) + root + job.public if xmss else (
             be(p.typecode) + be(p.lmots_typecode) + job.identifier + root)
    observed = {}
    if not stateful_shake.verify_serialized(name,message,signature,public,observed,hash_backend):
        raise AssertionError('Independent synthetic-path signature did not verify')
    nodes = (random,*chains,*auth)
    folder = Path(output)/p.name/'verify'
    compile_hardware_image(p.name,hash_backend=hash_backend).write(folder)
    cfg = [int.from_bytes(v,'little') for v in
           (job.secret,job.prf,job.public,job.random,root,job.identifier)] + [q,2,len(message)]
    mem(folder/'job.mem',cfg,64)
    mem(folder/'message.mem',message + bytes(87-len(message)),2)
    mem(folder/'nodes.mem',(int.from_bytes(v,'little') for v in nodes),64)
    mem(folder/'expected.mem',b'\0',2)
    mem(folder/'meta.mem',[0,observed['hashes'],observed['permutations'],len(nodes),1],16)
    return dict(profile=p.name,hash_backend=hash_backend,q=q,height=p.h,message_hex=message.hex(),
                synthetic_auth=True,full_tree_generated=False,public_root=root.hex(),
                public_key=public.hex(),signature=signature.hex(),independent_verify_passed=True,
                operations=[dict(operation='verify',output_bytes=0,hashes=observed['hashes'],
                                 permutations=observed['permutations'],sha256={
                                 n:hashlib.sha256((folder/n).read_bytes()).hexdigest() for n in MEM_FILES})])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='all', help='profile name or all; legacy omega names are retired')
    parser.add_argument('--hash', dest='hash_backend', choices=('shake','sha2'), default='shake')
    parser.add_argument('--output', type=Path, help='Default: tb/vectors for SHAKE, tb/vectors/sha2 for SHA2')
    parser.add_argument('--include-h20-full', action='store_true', help='Explicitly enable expensive h20 full-tree vector generation')
    parser.add_argument('--include-high-full', action='store_true', help='Explicitly enable h16/h15 complete-tree vector generation')
    parser.add_argument('--verify-only', action='store_true', help='Stateful real-height synthetic-path Verify; never computes a full tree')
    parser.add_argument('--job', type=Path, help='JSON fields or per-profile overrides')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--message-hex')
    group.add_argument('--message-length', type=int)
    parser.add_argument('--q', type=int)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if args.output is None:
        args.output=ROOT/'tb/vectors' if args.hash_backend=='shake' else ROOT/'tb/vectors/sha2'
    manifest=args.output/'generation.json'
    if manifest.exists() and json.loads(manifest.read_text()).get('hash_backend','shake') != args.hash_backend:
        parser.error('--output already contains vectors for the other hash backend')
    if args.profile != 'all':
        try:
            p=get_profile(args.profile,args.hash_backend)
            args.profile=p.name
            if p.stateful and p.h>10 and not args.verify_only and not args.include_high_full:
                parser.error('high-tree full generation is disabled; use --verify-only')
            if p.stateful and p.h==20 and not args.verify_only and not args.include_h20_full:
                parser.error('h20 full-tree generation is disabled; use --include-h20-full only when explicitly requested')
        except ValueError as e: parser.error(str(e))
    if not 1 <= args.workers <= 6:
        parser.error('--workers must be 1..6')
    if args.q is not None and not 0 <= args.q < (1 << 20):
        parser.error('--q outside selected tree')
    if args.message_length is not None and not 0 <= args.message_length <= 87:
        parser.error('--message-length must be 0..87 (SLH requires at least one byte)')
    defaults = json.loads((ROOT/'model/default_jobs.json').read_text())
    overrides = json.loads(args.job.read_text()) if args.job else {}
    names = list(profile_names(args.hash_backend,include_h20=args.include_h20_full or args.verify_only)) if args.profile == 'all' else [args.profile]
    if args.profile == 'all':
        names = [name for name in names if (get_profile(name,args.hash_backend).stateful if args.verify_only else
                 (args.include_high_full or not get_profile(name,args.hash_backend).stateful or get_profile(name,args.hash_backend).h==10))]
    tasks = []
    for name in names:
        config = dict(defaults[name])
        fields={'secret_seed','secret_prf','public_seed','randomizer','identifier','q','message'}
        config.update(overrides if set(overrides)&fields else overrides.get(name, {}))
        if args.q is not None:
            config['q'] = args.q
        if args.message_hex is not None:
            config['message'] = args.message_hex
        elif args.message_length is not None:
            first = bytes.fromhex(config['message'])[0]
            config['message'] = bytes((first+i)&255 for i in range(args.message_length)).hex()
        tasks.append((name,config,str(args.output.resolve()),args.hash_backend))
    args.output.mkdir(parents=True, exist_ok=True)
    rows=[]
    if not args.verify_only and any(get_profile(name).stateful for name in names):
        from scripts.build_stateful_reference import build
        build()  # Build once before workers; each process owns its native counters.
    with ProcessPoolExecutor(max_workers=min(args.workers,len(tasks))) as pool:
        futures=[pool.submit(generate_verify_profile if args.verify_only else generate_profile,*task) for task in tasks]
        for future in futures:
            row=future.result();rows.append(row)
            print('VECTOR_PASS',row['profile'],'verify' if args.verify_only else 'keygen/sign/verify',flush=True)
    path=args.output/'generation.json'
    existing = json.loads(path.read_text()).get('profiles', []) if path.exists() else []
    merged={r['profile']:r for r in existing if r['profile'] in PROFILES}
    merged.update({r['profile']:r for r in rows})
    result = dict(schema='mhbs.independent_vectors.v3',hash_backend=args.hash_backend,profiles=list(merged.values()),
                  python_stdlib_only=not any(get_profile(name).stateful for name in names),
                  stateful_oracle="pinned independent C; actual primitive-call counters",existing_vectors_required=False)
    path=args.output/'generation.json'
    temporary=path.with_suffix(f'.{__import__("os").getpid()}.json.tmp')
    temporary.write_text(json.dumps(result,indent=2)+'\n');temporary.replace(path)
    print('VECTOR_GENERATION_PASS',len(rows)*3,'cases',flush=True)


if __name__ == '__main__':
    main()
