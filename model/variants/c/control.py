"""Layout-4 explicit tree control for main-compatible task templates.

Control words update one narrow context or one node.  They never issue hashes
or advance a tree implicitly.  Macro words retain main's low-17-bit template.
"""
from enum import IntEnum

PROGRAM_WORDS = 128
TEMPLATE_WORDS = 32
DESCRIPTOR_WORDS = 32
HEADER_MAGIC = 0x53
KEEP_COORD = 1 << 28

class Op(IntEnum):
    HALT=0; SET=1; MOV=2; INC=3; SHR=4; XOR1=5; ADD=6; BR=7
    CALL=8; RET=9; LOAD=10; STORE=11; INPUT=12; OUTPUT=13; WMOV=14; SHL=15

class Ctx(IntEnum):
    LEAF=0; A=1; B=2; CURSOR=3; INDEX=4; LEVEL=5; TARGET=6; PATH=7
    BASE=8; HEIGHT=9; LIMIT=10; LAYER=11; GROUP=12; AUTH_LEVEL=13
    FLAGS=14; MODE=15; Q=16; SCALAR_LEAF=17; FORS_TARGET=18
    PROFILE_HEIGHT=19; ZERO=20; ONE=21; OPERATION=22; XMSS=23; STATEFUL=24

class Wide(IntEnum):
    NODE=0; LEFT=1; V0=2; V1=3; V2=4; V3=5; EMIT=6; ZERO=7

class Cond(IntEnum):
    ALWAYS=0; EQ=1; NE=2; LT=3; GE=4; ODD=5; ZERO=6; BITSET=7
    SIBLING=8; SAME_PARENT=9

STACK_BASE=68
AUTH_BASE=88

def control(op, dst=0, src=0, aux=0, imm=0, target=0, cond=0):
    for value,width in ((op,5),(dst,5),(src,5),(aux,5),(imm,21),(target,7),(cond,4)):
        if not 0 <= int(value) < (1 << width):
            raise ValueError('control field overflow')
    return (3 << 62) | (int(op)<<57) | (int(dst)<<52) | (int(src)<<47) | \
           (int(aux)<<42) | (int(imm)<<21) | (int(target)<<14) | (int(cond)<<10)

def fields(word):
    return (Op((word>>57)&31),(word>>52)&31,(word>>47)&31,(word>>42)&31,
            (word>>21)&0x1fffff,(word>>14)&127,Cond((word>>10)&15))

def macro(tid, layer=0, group=0, keep=True):
    if not 0 <= tid < TEMPLATE_WORDS:
        raise ValueError('template capacity')
    return ((tid&15)<<58) | ((tid>>4)<<29) | ((layer<<6|group)<<47) | (KEEP_COORD if keep else 0)

def template_id(word):
    return ((word>>58)&15) | (((word>>29)&1)<<4)
