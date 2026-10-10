#!/usr/bin/env python3
"""Build pinned independent validation implementations, with explicit LMS adapter."""
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PINS = {'xmss': ('https://github.com/XMSS/xmss-reference.git',
                  '171ccbd26f098542a67eb5d2b128281c80bd71a6'),
        'lms': ('https://github.com/cisco/hash-sigs.git',
                'cea4dda4f937e56ab42e1a74665f6397473a2838')}

def build():
    out = ROOT/'build/reference_native'
    out.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256((Path(__file__).read_bytes()+
        (ROOT/'scripts/reference_stateful.c').read_bytes())).hexdigest()
    lib=out/'reference.so'
    if lib.exists() and (out/'identity.txt').exists() and (out/'identity.txt').read_text()==identity:
        return lib
    patches=[]
    for name,(url,commit) in PINS.items():
        checkout=ROOT/f'build/reference_{name}'
        if not checkout.exists():
            subprocess.run(['git','clone',url,str(checkout)],check=True)
        if subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout,text=True).strip()!=commit:
            subprocess.run(['git','fetch','origin',commit],cwd=checkout,check=True)
            subprocess.run(['git','checkout','--detach',commit],cwd=checkout,check=True)
        dest=out/name
        dest.mkdir(exist_ok=True)
        for p in checkout.iterdir():
            if p.suffix in ('.c','.h'):
                shutil.copyfile(p,dest/p.name)
    def change(name, fn):
        p=out/name;old=p.read_text();new=fn(old);p.write_text(new)
        patches.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),
                                          fromfile='a/'+name,tofile='b/'+name))
    change('xmss/hash.c',lambda s:s.replace('    unsigned char buf[64];',
        '    extern void ref_count(size_t);\n    ref_count(inlen);\n    unsigned char buf[64];',1))
    # Upstream erases the last-index key before using it. Keep the valid final
    # leaf available to the validation signer; exhausted indices remain rejected.
    change('xmss/xmss_core.c',lambda s:s.replace(
        'if (idx >= ((1ULL << params->full_height) - 1))',
        'if (idx > ((1ULL << params->full_height) - 1))'))
    change('lms/hash.h',lambda s:s.replace('#include "sha256.h"',
        '#include "sha256.h"\n#include <openssl/evp.h>').replace('    HASH_SHA256 = 1,',
        '    HASH_SHAKE256 = 2,\n    HASH_SHA256 = 1,').replace('    SHA256_CTX sha256;',
        '    SHA256_CTX sha256;\n    struct { EVP_MD_CTX *shake; size_t shake_bytes; };'))
    change('lms/lm_ots_common.c',lambda s:s.replace('    default: return false;',
        '    case 0x0b: v_h = HASH_SHAKE256; v_n = 32; v_w = 4; v_p = 67; v_ls = 4; break;\n    default: return false;',1))
    change('lms/lm_common.c',lambda s:s.replace('    default: return false;',
        '    case 0x10: v_h = HASH_SHAKE256; v_n = 32; v_height = 10; break;\n'
        '    case 0x11: v_h = HASH_SHAKE256; v_n = 32; v_height = 15; break;\n'
        '    case 0x12: v_h = HASH_SHAKE256; v_n = 32; v_height = 20; break;\n    default: return false;',1))
    xmss=['params.c','hash.c','fips202.c','hash_address.c','randombytes.c','wots.c',
          'xmss_core.c','xmss_commons.c','utils.c']
    lms=['lm_common.c','lm_ots_common.c','lm_ots_verify.c','lm_verify.c','endian.c']
    cmd=['gcc','-O3','-march=native','-fPIC','-shared','-Wno-deprecated-declarations',
         '-I'+str(out),'-I'+str(out/'xmss'),'-I'+str(out/'lms'),
         str(ROOT/'scripts/reference_stateful.c'),
         *[str(out/'xmss'/f) for f in xmss],*[str(out/'lms'/f) for f in lms],'-lcrypto','-o',str(lib)]
    with (out/'compile.log').open('w') as log:
        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
    (out/'adapter.patch').write_text(''.join(patches))
    files=[*list((out/'xmss').glob('*.[ch]')),*list((out/'lms').glob('*.[ch]')),
           ROOT/'scripts/reference_stateful.c']
    (out/'manifest.json').write_text(json.dumps(dict(pins=PINS,command=cmd,
        sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}),indent=2)+'\n')
    (out/'identity.txt').write_text(identity)
    return lib

if __name__=='__main__':
    print(build())
