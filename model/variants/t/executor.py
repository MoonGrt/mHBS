"""Executable HBS image ABI 4: 128-bit tokens/templates, 64-bit descriptors.

The interpreter executes the same five macro operations for every image. It
does not call an algorithm oracle. hashlib supplies the hash primitives.
Recipe shapes describe byte construction, including compound masked hashes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable
from model.profiles import get_profile
from model.hashes import block_count, digest

from model.microcode import (
    StaticTaskToken as Token, TOKEN_SINGLE, TOKEN_RUN, TOKEN_LOOP, TOKEN_HALT,
    issue_word, expand,
)


class Macro(IntEnum):
    HASH = 1
    CHAIN = 2
    TREE = 3
    TRANSFORM = 4
    EMIT = 5


class Kind(IntEnum):
    HASH = 1
    SEGMENT = 2
    CHAIN = 4
    TREE = 5
    ROUTE = 6
    TRANSFORM = 8
    EMIT = 9
    IMAGE = 10
    PROFILE = 11


class Shape(IntEnum):
    ADDRESS_SEED = 1
    ADDRESS_VALUE = 2
    MESSAGE_PRF = 3
    MESSAGE_DIGEST = 4
    INDEX_PRF = 5
    ROOT_MESSAGE = 6
    MASKED_SEED = 7
    MASKED_VALUE = 8
    PREFIX_SEED = 9
    PREFIX_VALUE = 10
    PREFIX_MESSAGE = 11
    ADDRESS_LIST = 12
    PREFIX_LIST = 13
    PREFIX_LEAF = 14
    PREFIX_PARENT = 15


class Source(IntEnum):
    SECRET = 0
    PRF = 1
    PUBLIC = 2
    ROOT = 3
    RANDOM = 4
    IDENTIFIER = 5
    INDEX = 6
    CONSTANT = 7


CAPTURE, AUTH, SIGN_ONLY, EXTERNAL_ROOT = 1, 2, 4, 8


def record(kind: Kind, **fields: tuple[int, int, int]) -> int:
    word = int(kind) << 60
    used = 0
    for name, (value, shift, bits) in fields.items():
        mask = ((1 << bits) - 1) << shift
        if value < 0 or value >= 1 << bits or mask & used or shift + bits > 60:
            raise ValueError(f"invalid or overlapping {kind.name}.{name}")
        word |= value << shift
        used |= mask
    return word


def field(word: int, shift: int, bits: int) -> int:
    return (word >> shift) & ((1 << bits) - 1)


def recipe(shape: Shape, n: int, domain: int = 0, arity: int = 1,
           blocks: int = 1) -> int:
    return record(Kind.HASH, shape=(shape, 56, 4), domain=(domain, 48, 8),
                  arity=(arity, 40, 8), output=(n, 32, 6), blocks=(blocks, 24, 6))


def chain(seed: int, step: int, count: int, steps: int,
          reduce: int = 0, leaf: int = 0, mode: int = 0) -> int:
    return record(Kind.CHAIN, seed=(seed, 52, 8), step=(step, 44, 8),
                  reduce=(reduce, 36, 8), leaf=(leaf, 28, 8), count=(count, 20, 8),
                  steps=(steps, 15, 5), mode=(mode, 12, 2))


def tree(chain_id: int, parent: int, height: int, target: int = 0,
         indexing: int = 0, cache: bool = False, lookup: bool = False,
         full_cache: bool = False) -> int:
    return record(Kind.TREE, chain=(chain_id, 52, 8), parent=(parent, 44, 8),
                  height=(height & 15, 40, 4), height_high=(height >> 4, 39, 1), target=(target, 36, 2),
                  indexing=(indexing, 32, 2), cache=(int(cache), 31, 1),
                  lookup=(int(lookup), 30, 1), full_cache=(int(full_cache), 29, 1))


def route(slot: int, emit: bool = False, parse: bool = False,
          group: bool = False) -> int:
    return record(Kind.ROUTE, slot=(slot, 56, 2), emit=(int(emit), 55, 1),
                  parse=(int(parse), 54, 1), group=(int(group), 53, 1))


def segment(source: Source, length: int, value: int = 0) -> int:
    return record(Kind.SEGMENT, source=(source, 56, 4), length=(length, 48, 8),
                  constant=(value, 0, 32))


def command(op: Macro, desc: int, result: int = 0, flags: int = 0) -> int:
    return (int(op) << 44) | (desc << 36) | (result << 28) | (flags << 24)


@dataclass(frozen=True)
class Image:
    name: str
    tokens: tuple[int, ...]
    templates: tuple[int, ...]
    descriptors: tuple[int, ...]
    # Software metadata, separate from the descriptor's height bits.
    hash_backend: str = "shake"

    @property
    def n(self) -> int:
        return field(self.descriptors[1], 48, 8)

    @property
    def stateful(self) -> bool:
        return bool(field(self.descriptors[1], 59, 1))

    @property
    def omega(self): return field(self.descriptors[1], 44, 4)

    @property
    def hp(self): return self.h if self.stateful else field(self.descriptors[1], 40, 4)

    @property
    def a(self): return field(self.descriptors[1], 36, 4)

    @property
    def k(self): return field(self.descriptors[1], 18, 6)

    @property
    def h(self): return field(self.descriptors[1], 0, 7)

    @property
    def m(self): return field(self.descriptors[1], 7, 6)

    def entry(self, sign: bool) -> int:
        return field(self.descriptors[0], 38 if sign else 47, 9)

    def output_bytes(self, sign: bool) -> int:
        return field(self.descriptors[0], 0 if sign else 18, 18)

    def words(self, sign: bool) -> tuple[int, ...]:
        objects = []
        for raw in self.tokens[self.entry(sign):]:
            kind = raw >> 126
            if kind == TOKEN_HALT:
                if raw != 3 << 126:
                    raise ValueError("HALT reserved bits")
                objects.append(Token(kind))
                break
            if kind == TOKEN_LOOP:
                if raw & ((1 << 60) - 1):
                    raise ValueError("LOOP reserved bits")
                t = Token(kind, back_count=field(raw, 114, 12)+1,
                          loop_repeats=field(raw, 108, 6),
                          delta0=field(raw, 84, 24), delta1=field(raw, 60, 24))
                if t.back_count > len(objects):
                    raise ValueError("LOOP escapes entry")
            else:
                if raw & ((1 << 18) - 1):
                    raise ValueError("token reserved bits")
                t = Token(kind, template=field(raw, 120, 6),
                          coord0=field(raw, 96, 24), coord1=field(raw, 72, 24),
                          repeat=field(raw, 66, 6)+1,
                          stride0=field(raw, 42, 24), stride1=field(raw, 18, 24))
            t.encode()  # range and SINGLE/RUN consistency checks
            objects.append(t)
        if not objects or objects[-1].kind != TOKEN_HALT:
            raise ValueError("entry has no HALT")
        return tuple(expand(self.templates, objects))


def compile_image(name: str, *, full_cache: bool = False, hash_backend="shake") -> Image:
    """Compile one of seven static profiles; jobs are separate from images."""
    p = get_profile(name, hash_backend)
    name, n = p.family, p.n
    records = [0] * 128
    records[1] = record(Kind.PROFILE, stateful=(int(p.stateful), 59, 1),
        family=({"slh":1,"xmss":2,"lms":3}[name], 56, 3), n=(n,48,8),
        omega=(p.omega,44,4), height=(p.hp & 15,40,4), fors_a=(p.a,36,4),
        message_limit=(87,24,8), fors_k=(p.k,18,6), layers=(p.d,13,5),
        digest_bytes=(p.m,7,6), total_height=(p.h,0,7))
    records[40] = route(0, emit=True)
    records[41] = route(1, parse=True)
    records[42] = route(2)
    records[43] = route(2, group=True)
    records[44] = route(3)
    records[45] = route(0)
    records[48] = record(Kind.TRANSFORM, operation=(1, 56, 4), source=(2, 48, 2))
    records[49] = record(Kind.TRANSFORM, operation=(2, 56, 4), shift=(0 if p.stateful else p.hp, 40, 4))

    def emit(desc: int, base: int, parts: list[tuple]) -> None:
        records[desc] = record(Kind.EMIT, base=(base, 52, 8), count=(len(parts), 48, 4))
        for offset, args in enumerate(parts):
            records[base+offset] = segment(*args)

    templates: list[int] = []
    def single(op: Macro, desc: int, result: int = 0, flags: int = 0,
               coord: int = 0, first: bool = False, repeat: int = 1,
               stride: int = 0) -> Token:
        tid = len(templates)
        templates.append(issue_word(command(op, desc, result, flags), first=first))
        return Token(TOKEN_SINGLE if repeat == 1 else TOKEN_RUN,
                     template=tid, coord0=coord, repeat=repeat, stride0=stride)

    if name == "slh":
        for i, args in {
            2: (Shape.MESSAGE_PRF, n, 0, 1, (2*n+87)//136+1),
            3: (Shape.MESSAGE_DIGEST, p.m, 0, 1, (3*n+87)//136+1),
            4: (Shape.ADDRESS_SEED, n, 6), 5: (Shape.ADDRESS_VALUE, n, 3),
            6: (Shape.ADDRESS_VALUE, n, 3, 2),
            7: (Shape.ADDRESS_SEED, n, 5), 8: (Shape.ADDRESS_VALUE, n, 0),
            9: (Shape.ADDRESS_LIST, n, 1, p.chains, (n+32+n*p.chains)//136+1),
            10: (Shape.ADDRESS_VALUE, n, 2, 2),
            11: (Shape.ADDRESS_LIST, n, 4, p.k, (n+32+n*p.k)//136+1),
        }.items():
            records[i] = recipe(*args)
        records[16] = chain(4, 5, 1, 1)
        records[17] = chain(7, 8, p.chains, 15, reduce=9, mode=1)
        records[20] = tree(16, 6, p.a, target=1, indexing=1)
        records[21] = tree(17, 10, p.hp)
        emit(50, 64, [(Source.SECRET, n), (Source.PRF, n), (Source.PUBLIC, n),
                      (Source.ROOT, n), (Source.PUBLIC, n), (Source.ROOT, n)])
        kg = [single(Macro.TREE, 21, 44, coord=(p.d-1) << 19, first=True),
              single(Macro.EMIT, 50), Token(TOKEN_HALT)]
        sg = [single(Macro.HASH, 2, 40, first=True), single(Macro.HASH, 3, 41),
              single(Macro.TREE, 20, 43, CAPTURE|AUTH, repeat=p.k, stride=1 << 13),
              single(Macro.HASH, 11, 42), single(Macro.TRANSFORM, 48),
              single(Macro.TREE, 21, 42, CAPTURE|AUTH),
              single(Macro.TRANSFORM, 49), single(Macro.TRANSFORM, 48),
              Token(TOKEN_LOOP, back_count=3, loop_repeats=p.d-2, delta0=1 << 19),
              single(Macro.TREE, 21, 42, CAPTURE|AUTH|EXTERNAL_ROOT, coord=(p.d-1) << 19),
              Token(TOKEN_HALT)]
        kg_bytes, sg_bytes = p.keygen_bytes, p.signature_bytes
    else:
        masked = name == "xmss"
        recipes = ((Shape.INDEX_PRF, 32), (Shape.ROOT_MESSAGE, 32, 0, 1, 2),
                   (Shape.MASKED_SEED, 32), (Shape.MASKED_VALUE, 32, 0),
                   (Shape.MASKED_VALUE, 32, 1, 2), (Shape.MASKED_VALUE, 32, 2, 2)) \
            if masked else ((Shape.PREFIX_MESSAGE, 32, 0, 1, 2),
                            (Shape.PREFIX_SEED, 32), (Shape.PREFIX_VALUE, 32),
                            (Shape.PREFIX_LIST, 32, 0, p.chains, (22+32*p.chains)//136+1),
                            (Shape.PREFIX_LEAF, 32), (Shape.PREFIX_PARENT, 32, 0, 2))
        for i, args in enumerate(recipes, 2):
            records[i] = recipe(*args)
        records[16] = chain(4, 5, p.chains, (1 << p.omega)-1, reduce=6, mode=2) if masked \
            else chain(3, 4, p.chains, (1 << p.omega)-1, reduce=5, leaf=6, mode=1)
        records[20] = tree(16, 7, p.h, target=2, indexing=0 if masked else 2,
                           cache=True, full_cache=full_cache)
        records[21] = tree(16, 7, p.h, target=2, indexing=0 if masked else 2, lookup=True)
        parts = [(Source.CONSTANT, 4, p.typecode), (Source.ROOT, n), (Source.PUBLIC, n)] \
            if masked else [(Source.CONSTANT, 4, p.typecode), (Source.CONSTANT, 4, p.lmots_typecode),
                            (Source.IDENTIFIER, 16), (Source.ROOT, n)]
        emit(50, 64, parts)
        emit(51, 80, [(Source.INDEX, 4)] + ([] if masked else [(Source.CONSTANT, 4, p.lmots_typecode)])
             + [(Source.RANDOM, n)])
        if not masked:
            emit(52, 84, [(Source.CONSTANT, 4, p.typecode)])
        kg = [single(Macro.TREE, 20, 44, first=True), single(Macro.EMIT, 50), Token(TOKEN_HALT)]
        sg = [single(Macro.HASH, 2, 45 if masked else 42, first=True)]
        if masked:
            sg.append(single(Macro.HASH, 3, 42))
        sg += [single(Macro.TRANSFORM, 48), single(Macro.EMIT, 51),
               single(Macro.CHAIN, 16, flags=SIGN_ONLY)]
        if not masked:
            sg.append(single(Macro.EMIT, 52))
        sg += [single(Macro.TREE, 21, flags=AUTH), Token(TOKEN_HALT)]
        kg_bytes, sg_bytes = p.keygen_bytes, p.signature_bytes
    records[0] = record(Kind.IMAGE, version=(4, 56, 4), keygen=(0, 47, 9),
                        sign=(len(kg), 38, 9), kg_bytes=(kg_bytes, 18, 18),
                        sg_bytes=(sg_bytes, 0, 18))
    if hash_backend == "sha2":
        # Bounds apply to individual primitive invocations of compound recipes.
        maximum_lengths = {
            Shape.ADDRESS_SEED: 64 + 22 + n,
            Shape.ADDRESS_VALUE: 64 + 22 + 2*n,
            Shape.MESSAGE_PRF: 64 + n + 87,
            Shape.MESSAGE_DIGEST: max(3*n + 87, 2*n + 32 + 4),
            Shape.INDEX_PRF: 96, Shape.ROOT_MESSAGE: 128 + 87,
            Shape.MASKED_SEED: 128, Shape.MASKED_VALUE: 128,
            Shape.PREFIX_SEED: 55, Shape.PREFIX_VALUE: 55,
            Shape.PREFIX_MESSAGE: 54 + 87,
            Shape.PREFIX_LIST: 22 + n*p.chains,
            Shape.PREFIX_LEAF: 54, Shape.PREFIX_PARENT: 86,
        }
        for i, word in enumerate(records):
            if word >> 60 != Kind.HASH:
                continue
            shape = Shape(field(word, 56, 4))
            length = (64 + 22 + n*field(word, 40, 8)) if shape == Shape.ADDRESS_LIST else maximum_lengths[shape]
            records[i] = (word & ~(63 << 24)) | (block_count(length, hash_backend) << 24)
    image = Image(p.name, tuple(t.encode() for t in kg+sg), tuple(templates), tuple(records), hash_backend)
    validate(image)
    return image


def validate(image: Image) -> None:
    if image.hash_backend not in ('shake', 'sha2'):
        raise ValueError('unknown hash backend')
    d = image.descriptors
    if not 2 <= len(d) <= 256 or len(image.tokens) > 384 or len(image.templates) > 64:
        raise ValueError("image storage bounds")
    if any(x < 0 or x >= 1 << 64 for x in d):
        raise ValueError("descriptor width")
    if d[0] >> 60 != Kind.IMAGE or field(d[0], 56, 4) != 4:
        raise ValueError("unsupported image ABI")
    if d[1] >> 60 != Kind.PROFILE or image.n not in (16, 24, 32):
        raise ValueError("unsupported node size")
    if image.hash_backend == 'sha2' and not image.stateful and image.n != 16:
        raise ValueError('unsupported SHA2 SLH node size')
    family = field(d[1],56,3)
    if family not in (1,2,3) or image.stateful != (family != 1) or image.omega != 4:
        raise ValueError("invalid profile identity/Winternitz width")
    if image.stateful and (image.n != 32 or image.h not in ((10,16,20) if family==2 else (10,15,20)) or image.hp != image.h):
        raise ValueError("unsupported stateful profile")
    if not image.stateful and (image.omega != 4 or (image.n,image.h,image.hp,image.k,image.a,image.m) not in
            ((16,66,3,33,6,34),(24,66,3,33,8,42),(32,68,4,35,9,49),
             (16,63,9,14,12,30),(24,63,9,17,14,39),(32,64,8,22,14,47))):
        raise ValueError("unsupported stateless profile")
    if not 0 <= image.entry(False) < image.entry(True) < len(image.tokens):
        raise ValueError("invalid entry table")
    def ref(i: int, kind: Kind) -> int:
        if not 0 <= i < len(d) or d[i] >> 60 != kind:
            raise ValueError(f"descriptor {i}: expected {kind.name}")
        return d[i]
    for w in d:
        if not w:
            continue
        kind = Kind(w >> 60)
        if kind == Kind.HASH:
            Shape(field(w, 56, 4))
            if not 1 <= field(w, 32, 6) <= 49 or not 1 <= field(w, 24, 6) <= (63 if image.hash_backend == 'sha2' else 32):
                raise ValueError("recipe result/block bound")
        elif kind == Kind.CHAIN:
            for shift in (52, 44): ref(field(w, shift, 8), Kind.HASH)
            for shift in (36, 28):
                if field(w, shift, 8): ref(field(w, shift, 8), Kind.HASH)
            if not 1 <= field(w, 20, 8) <= 133 or field(w, 15, 5) > 15:
                raise ValueError("chain bound")
            if field(w, 12, 2) > 2:
                raise ValueError("chain reduction mode")
        elif kind == Kind.TREE:
            ref(field(w, 52, 8), Kind.CHAIN)
            ref(field(w, 44, 8), Kind.HASH)
            if not 1 <= (field(w, 40, 4) | (field(w,39,1)<<4)) <= (20 if image.stateful else 14):
                raise ValueError("tree height")
            if field(w, 36, 2) > 2 or field(w, 32, 2) > 2:
                raise ValueError("tree addressing mode")
        elif kind == Kind.EMIT:
            base, count = field(w, 52, 8), field(w, 48, 4)
            if not count:
                raise ValueError("empty emit")
            for i in range(base, base+count): ref(i, Kind.SEGMENT)
        elif kind == Kind.SEGMENT:
            source = Source(field(w, 56, 4))
            length = field(w, 48, 8)
            if not 1 <= length <= (4 if source in (Source.INDEX, Source.CONSTANT)
                                   else 16 if source == Source.IDENTIFIER else image.n):
                raise ValueError("segment length")
    for sign in (False, True):
        words = image.words(sign)
        allocated = False
        for word in words[:-1]:
            if word >> 124 != 1 or not field(word, 107, 1) or field(word, 106, 1):
                raise ValueError("exclusive macro template required")
            if field(word, 116, 8) != int(allocated) or field(word, 108, 8) != int(allocated):
                raise ValueError("macro event dependency")
            if field(word, 103, 3) or (word & 0xf) != 8:
                raise ValueError("macro completion event")
            allocated = True
            op = Macro(field(word, 96, 4))
            ref(field(word, 88, 8), {Macro.HASH: Kind.HASH, Macro.CHAIN: Kind.CHAIN,
                Macro.TREE: Kind.TREE, Macro.TRANSFORM: Kind.TRANSFORM, Macro.EMIT: Kind.EMIT}[op])
            rid = field(word, 80, 8)
            if rid: ref(rid, Kind.ROUTE)


@dataclass(frozen=True)
class Job:
    secret: bytes
    prf: bytes
    public: bytes
    random: bytes
    identifier: bytes = bytes(16)
    q: int = 0


class Machine:
    def __init__(self, image: Image, job: Job,
                 observe: Callable[[int, bytes, bytes], None] | None = None,
                 *, index_policy: str = "guarded", recompute_auth: bool = False):
        if index_policy not in ("guarded", "fixed_q_no_guard"):
            raise ValueError("index policy")
        self.recompute_auth = recompute_auth
        self.index_policy = index_policy
        validate(image)
        if any(len(v) != image.n for v in (job.secret, job.prf, job.public, job.random)):
            raise ValueError("job node width")
        if len(job.identifier) != 16 or not (0 <= job.q < (1 << image.h) if image.stateful else job.q == 0):
            raise ValueError("job identifier/index")
        self.image, self.job, self.n, self.observe = image, job, image.n, observe
        self.values = [bytes(image.m) for _ in range(4)]
        self.roots: dict[int, bytes] = {}
        self.cache: dict[tuple[int, int], bytes] = {}
        self.cache_valid = False
        self.cache_q = job.q
        self.q = job.q
        self.hashes = self.permutations = 0
        self.digits: list[int] = []
        self.scalar_tree = self.scalar_leaf = 0
        self.output = bytearray()
        self.message = b""
        self.trace: list[tuple[int, int, int, int]] = []

    def _hash(self, rid: int, data: bytes, length: int | None = None) -> bytes:
        r = self.image.descriptors[rid]
        blocks = block_count(len(data), self.image.hash_backend)
        if blocks > field(r, 24, 6):
            raise ValueError("recipe exceeds block bound")
        result = digest(data, length or field(r, 32, 6), self.image.hash_backend)
        self.hashes += 1
        self.permutations += blocks
        if self.observe: self.observe(rid, data, result)
        return result

    def hash_recipe(self, rid: int, *, layer: int = 0, leaf: int = 0,
                    a: int = 0, b: int = 0, left: bytes = b"", right: bytes = b"",
                    values: list[bytes] | None = None) -> bytes:
        r = self.image.descriptors[rid]
        shape, domain, arity = Shape(field(r, 56, 4)), field(r, 48, 8), field(r, 40, 8)
        j = self.job
        def be(x: int, count: int = 4) -> bytes: return x.to_bytes(count, "big")
        address = b"".join(be(x) for x in (layer, 0, self.scalar_tree >> 32,
            self.scalar_tree & 0xffffffff, domain, leaf, a, b))
        mask_address = b"".join(be(x) for x in (0, 0, 0, domain, leaf, a, b))
        if self.image.hash_backend == "sha2" and not self.image.stateful:
            compressed = address[3:4] + address[8:16] + address[19:20] + address[20:32]
            prefix = j.public + bytes(64-self.n) + compressed
            if shape == Shape.ADDRESS_SEED:
                return self._hash(rid, prefix + j.secret)
            if shape == Shape.ADDRESS_VALUE:
                return self._hash(rid, prefix + left + (right if arity == 2 else b""))
            if shape == Shape.ADDRESS_LIST:
                return self._hash(rid, prefix + b"".join(values or []))
            if shape == Shape.MESSAGE_PRF:
                key = j.prf.ljust(64, b"\0")
                inner = self._hash(rid, bytes(x ^ 0x36 for x in key) + j.random + self.message, 32)
                return self._hash(rid, bytes(x ^ 0x5c for x in key) + inner, self.n)
            if shape == Shape.MESSAGE_DIGEST:
                random = self.values[0][:self.n]
                inner = self._hash(rid, random + j.public + self.values[3][:self.n] + self.message, 32)
                seed = random + j.public + inner
                output = b"".join(self._hash(rid, seed + be(i), 32) for i in range((self.image.m+31)//32))
                return output[:self.image.m]
        if shape == Shape.ADDRESS_SEED: data = j.public + address + j.secret
        elif shape == Shape.ADDRESS_VALUE: data = j.public + address + left + (right if arity == 2 else b"")
        elif shape == Shape.MESSAGE_PRF: data = j.prf + j.random + self.message
        elif shape == Shape.MESSAGE_DIGEST: data = self.values[0][:self.n] + j.public + self.values[3][:self.n] + self.message
        elif shape == Shape.INDEX_PRF: data = be(3, self.n) + j.prf + be(self.active_q, 32)
        elif shape == Shape.ROOT_MESSAGE: data = be(2, self.n) + self.values[0][:self.n] + self.values[3][:self.n] + be(self.active_q, self.n) + self.message
        elif shape == Shape.MASKED_SEED: data = be(4, self.n) + j.secret + j.public + mask_address + be(0)
        elif shape == Shape.MASKED_VALUE:
            key = self._hash(rid, be(3, self.n) + j.public + mask_address + be(0))
            masks = b"".join(self._hash(rid, be(3, self.n) + j.public + mask_address + be(k)) for k in range(1, arity+1))
            value = left + (right if arity == 2 else b"")
            data = be(arity-1, self.n) + key + bytes(x ^ y for x, y in zip(value, masks, strict=True))
        elif shape == Shape.PREFIX_SEED: data = j.identifier + be(leaf) + be(a, 2) + b"\xff" + j.secret
        elif shape == Shape.PREFIX_VALUE: data = j.identifier + be(leaf) + be(a, 2) + be(b, 1) + left
        elif shape == Shape.PREFIX_MESSAGE: data = j.identifier + be(self.active_q) + b"\x81\x81" + j.random + self.message
        elif shape == Shape.ADDRESS_LIST: data = j.public + address + b"".join(values or [])
        elif shape == Shape.PREFIX_LIST: data = j.identifier + be(leaf) + b"\x80\x80" + b"".join(values or [])
        elif shape == Shape.PREFIX_LEAF: data = j.identifier + be(b) + b"\x82\x82" + left
        elif shape == Shape.PREFIX_PARENT: data = j.identifier + be(b) + b"\x83\x83" + left + right
        else: raise ValueError("unimplemented recipe")
        return self._hash(rid, data)

    def chains(self, did: int, layer: int, leaf: int, index: int,
               fors: bool, capture: bool, sign_only: bool) -> bytes:
        d = self.image.descriptors[did]
        seed, step, reduce, leaf_recipe = (field(d, s, 8) for s in (52, 44, 36, 28))
        count, steps, mode = field(d, 20, 8), field(d, 15, 5), field(d, 12, 2)
        endpoints = []
        for item in range(count):
            b = index if fors else 0
            value = self.hash_recipe(seed, layer=layer, leaf=leaf, a=item, b=b)
            digit = 0 if fors else self.digits[item] if capture or sign_only else steps
            if (capture or sign_only) and digit == 0: self.output.extend(value)
            for iteration in range(digit if sign_only else steps):
                value = self.hash_recipe(step, layer=layer, leaf=leaf, a=item,
                    b=b if fors else iteration, left=value)
                if (capture or sign_only) and iteration+1 == digit: self.output.extend(value)
            endpoints.append(value)
        if sign_only:
            return bytes(self.n)
        if mode == 1:
            value = self.hash_recipe(reduce, layer=layer, leaf=leaf, values=endpoints)
        elif mode == 2:
            level = 0
            while len(endpoints) > 1:
                endpoints = [self.hash_recipe(reduce, leaf=leaf, a=level, b=i//2,
                    left=endpoints[i], right=endpoints[i+1]) for i in range(0, len(endpoints)-1, 2)] \
                    + (endpoints[-1:] if len(endpoints) & 1 else [])
                level += 1
            value = endpoints[0]
        else: value = endpoints[0]
        if leaf_recipe:
            value = self.hash_recipe(leaf_recipe, leaf=leaf, b=index, left=value)
        return value

    def tree(self, did: int, flags: int, coord: int) -> bytes:
        d = self.image.descriptors[did]
        cid, parent, height = field(d, 52, 8), field(d, 44, 8), (field(d, 40, 4) | (field(d,39,1)<<4))
        target_mode, indexing = field(d, 36, 2), field(d, 32, 2)
        layer, group = coord >> 19, (coord >> 13) & 63
        target = self.active_q if target_mode == 2 else self.scalar_leaf
        if target_mode == 1:
            fb = (self.image.k*self.image.a+7)//8
            digest = int.from_bytes(self.values[1][:fb], "big")
            target = (digest >> (8*fb-self.image.a*(group+1))) & ((1<<self.image.a)-1)
        if field(d, 30, 1):
            if not self.cache_valid: raise ValueError("authentication cache is invalid")
            for level in range(height): self.output.extend(self.cache[level, (target >> level) ^ 1])
            return self.values[3][:self.n]
        nodes = []
        for i in range(1 << height):
            leaf = self.scalar_leaf if indexing == 1 else i
            index = group*(1 << height)+i if indexing == 1 else (1 << height)+i if indexing == 2 else i
            capture = bool(flags & CAPTURE) and i == target
            sign_only = capture and bool(flags & EXTERNAL_ROOT)
            nodes.append(self.chains(cid, layer, leaf, index, indexing == 1, capture, sign_only))
        for level in range(height+1):
            if field(d, 31, 1):
                self.cache_q = target
                for i, value in enumerate(nodes):
                    if field(d, 29, 1) or level == height or i == ((target >> level) ^ 1):
                        self.cache[level, i] = value
            if level == height: break
            if flags & AUTH: self.output.extend(nodes[(target >> level) ^ 1])
            next_nodes = []
            for i in range(len(nodes)//2):
                index = (group*(1 << height) >> (level+1))+i if indexing == 1 \
                    else (1 << (height-level-1))+i if indexing == 2 else i
                if flags & EXTERNAL_ROOT and i == target >> (level+1):
                    value = bytes(self.n)
                else:
                    a = level if Shape(field(self.image.descriptors[parent], 56, 4)) == Shape.MASKED_VALUE else level+1
                    value = self.hash_recipe(parent, layer=layer,
                        leaf=self.scalar_leaf if indexing == 1 else 0,
                        a=a, b=index, left=nodes[2*i], right=nodes[2*i+1])
                next_nodes.append(value)
            nodes = next_nodes
        if field(d, 31, 1): self.cache_valid = True
        return self.values[3][:self.n] if flags & EXTERNAL_ROOT else nodes[0]

    def run(self, sign: bool, message: bytes = b"", *, commit: bool = True) -> bytes:
        if sign and not (0 if self.image.stateful else 1) <= len(message) <= 87:
            raise ValueError("message length")
        if sign and self.image.stateful:
            if not self.recompute_auth and not self.cache_valid: raise ValueError("keygen required")
            if self.q >= (1 << self.image.h): raise ValueError("index exhausted")
            if not self.recompute_auth and not field(self.image.descriptors[20], 29, 1) and self.q != self.cache_q:
                raise ValueError("authentication cache belongs to another index")
            if self.index_policy == "guarded" and not commit:
                raise ValueError("state commit required before execution/output")
        self.active_q = self.q
        if sign and self.image.stateful and self.index_policy == "guarded":
            self.q += 1  # historical guarded policy: never rolled back
        if not sign:
            self.cache_valid = False
            self.cache.clear()
            self.roots.clear()
        self.output = bytearray()
        self.hashes = self.permutations = 0
        self.scalar_tree = self.scalar_leaf = 0
        self.message = message
        self.trace = []
        try:
            for word in self.image.words(sign)[:-1]:
                op, did, rid, flags, coord = (field(word, s, b) for s, b in
                    ((96, 4), (88, 8), (80, 8), (76, 4), (52, 24)))
                self.trace.append((op, did, flags, coord))
                d = self.image.descriptors[did]
                result = bytes(self.n)
                if op == Macro.HASH:
                    result = self.hash_recipe(did, leaf=self.scalar_leaf,
                                              values=[self.roots[k] for k in sorted(self.roots)])
                elif op == Macro.CHAIN:
                    result = self.chains(did, coord >> 19, self.active_q, 0, False,
                                         bool(flags & CAPTURE), bool(flags & SIGN_ONLY))
                elif op == Macro.TREE: result = self.tree(did, flags, coord)
                elif op == Macro.TRANSFORM:
                    if field(d, 56, 4) == 1:
                        value = self.values[field(d, 48, 2)][:self.n]
                        omega = self.image.omega
                        mask = (1 << omega)-1
                        self.digits = [(x >> shift) & mask for x in value
                                       for shift in range(8-omega, -1, -omega)]
                        checksum = sum(mask-x for x in self.digits)
                        len2 = (len(self.digits)*mask).bit_length() // omega + 1
                        self.digits += [(checksum >> shift) & mask
                                        for shift in range((len2-1)*omega, -1, -omega)]
                    elif field(d, 56, 4) == 2:
                        shift = field(d, 40, 4)
                        self.scalar_leaf = self.scalar_tree & ((1 << shift)-1)
                        self.scalar_tree >>= shift
                    else: raise ValueError("transform operation")
                elif op == Macro.EMIT:
                    for i in range(field(d, 52, 8), field(d, 52, 8)+field(d, 48, 4)):
                        seg = self.image.descriptors[i]
                        src, length = Source(field(seg, 56, 4)), field(seg, 48, 8)
                        value = {Source.SECRET:self.job.secret, Source.PRF:self.job.prf,
                            Source.PUBLIC:self.job.public, Source.ROOT:self.values[3],
                            Source.RANDOM:self.values[0] if self.image.descriptors[2] >> 56 & 15 == Shape.INDEX_PRF else self.job.random,
                            Source.IDENTIFIER:self.job.identifier,
                            Source.INDEX:self.active_q.to_bytes(4, "big"),
                            Source.CONSTANT:field(seg, 0, 32).to_bytes(4, "big")}[src]
                        self.output.extend(value[:length])
                else: raise ValueError("macro operation")
                if rid:
                    r = self.image.descriptors[rid]
                    if field(r, 53, 1): self.roots[(coord >> 13) & 63] = result
                    else: self.values[field(r, 56, 2)] = result
                    if field(r, 55, 1): self.output.extend(result)
                    if field(r, 54, 1):
                        fb = (self.image.k*self.image.a+7)//8
                        tb = (self.image.h-self.image.hp+7)//8
                        self.scalar_tree = int.from_bytes(result[fb:fb+tb], "big") & ((1 << (self.image.h-self.image.hp))-1)
                        lb = (self.image.hp+7)//8
                        self.scalar_leaf = int.from_bytes(result[fb+tb:fb+tb+lb], "big") & ((1<<self.image.hp)-1)
            if len(self.output) != self.image.output_bytes(sign):
                raise ValueError("output length")
            return bytes(self.output)
        except Exception:
            self.output.clear()
            self.cache_valid = False
            raise
