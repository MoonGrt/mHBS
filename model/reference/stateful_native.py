"""Pinned native independent standard oracle. Counters record actual hash calls."""
import ctypes
from scripts.build_stateful_reference import build
from model.profiles import get_profile

def generate(name, job, message, hash_backend="shake"):
    p=get_profile(name, hash_backend)
    backend=1 if hash_backend=='sha2' else 2
    lib=ctypes.CDLL(str(build()))
    u8=ctypes.c_ubyte
    def array(data): return (u8*len(data)).from_buffer_copy(data)
    pk=(u8*p.keygen_bytes)();sig=(u8*p.signature_bytes)();counts=(ctypes.c_uint64*4)()
    if p.family=='xmss':
        fn=lib.ref_xmss_generate
        fn.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_void_p,
                     ctypes.c_size_t,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p]
        status=fn(backend,p.h,job.q,array(job.secret+job.prf+job.public),array(message),len(message),pk,sig,counts)
    else:
        fn=lib.ref_lms_generate
        fn.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_uint32,*([ctypes.c_void_p]*4),ctypes.c_size_t,
                     *([ctypes.c_void_p]*3)]
        status=fn(backend,p.h,job.q,array(job.secret),array(job.identifier),array(job.random),
                  array(message),len(message),pk,sig,counts)
    if status: raise AssertionError(f'{name}: native reference status {status}')
    return bytes(pk),bytes(sig),list(counts)
