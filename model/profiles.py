"""Static product parameters. omega is bits per Winternitz digit."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Profile:
    name: str
    family: str
    n: int
    omega: int
    h: int
    hp: int
    d: int
    k: int
    a: int
    m: int
    target: float
    hash_backend: str = "shake"

    @property
    def stateful(self):
        return self.family != "slh"

    @property
    def len1(self):
        return 8 * self.n // self.omega

    @property
    def len2(self):
        return (self.len1 * ((1 << self.omega)-1)).bit_length() // self.omega + 1

    @property
    def chains(self):
        return self.len1 + self.len2

    @property
    def signature_bytes(self):
        if self.family == "slh":
            return self.n * (1 + self.k*(self.a+1) + self.d*(self.chains+self.hp))
        return (4 if self.family == "xmss" else 12) + self.n*(1+self.chains+self.h)

    @property
    def hardware_keygen_bytes(self):
        return self.keygen_bytes if self.family == "slh" else self.n

    @property
    def hardware_signature_bytes(self):
        return self.signature_bytes if self.family == "slh" else self.n*(1+self.chains+self.h)

    @property
    def keygen_bytes(self):
        return 6*self.n if self.family == "slh" else 196 if self.family == "xmss" else 140

    @property
    def public_key_bytes(self):
        return 2*self.n if self.family == "slh" else 68 if self.family == "xmss" else 56

    @property
    def typecode(self):
        if not self.stateful: raise ValueError("SLH has no XMSS/LMS type code")
        if self.hash_backend == "sha2":
            return {10:1,16:2,20:3}[self.h] if self.family == "xmss" else {10:6,15:7,20:8}[self.h]
        return {10:0x10,16:0x11,20:0x12}[self.h] if self.family == "xmss" else {10:0x10,15:0x11,20:0x12}[self.h]

    @property
    def lmots_typecode(self):
        return 3 if self.hash_backend == "sha2" else 0x0b

    @property
    def lanes(self):
        return 2 if self.family == "slh" else 1


PROFILES = {p.name: p for p in (
    Profile("slh_128f", "slh", 16, 4, 66, 3, 22, 33, 6, 34, 57360.476),
    Profile("slh_192f", "slh", 24, 4, 66, 3, 22, 33, 8, 42, 98729.547),
    Profile("slh_256f", "slh", 32, 4, 68, 4, 17, 35, 9, 49, 205686.556),
    Profile("slh_128s", "slh", 16, 4, 63, 9, 7, 14, 12, 30, 0),
    Profile("slh_192s", "slh", 24, 4, 63, 9, 7, 17, 14, 39, 0),
    Profile("slh_256s", "slh", 32, 4, 64, 8, 8, 22, 14, 47, 0),
    Profile("xmss_h10", "xmss", 32, 4, 10, 10, 1, 0, 0, 32, 0),
    Profile("xmss_h16", "xmss", 32, 4, 16, 16, 1, 0, 0, 32, 0),
    Profile("xmss_h20", "xmss", 32, 4, 20, 20, 1, 0, 0, 32, 0),
    Profile("lms_h10", "lms", 32, 4, 10, 10, 1, 0, 0, 32, 0),
    Profile("lms_h15", "lms", 32, 4, 15, 15, 1, 0, 0, 32, 0),
    Profile("lms_h20", "lms", 32, 4, 20, 20, 1, 0, 0, 32, 0),
)}
# Public names select the standardized h10 parameters.
ALIASES = {"slh": "slh_128f", "xmss": "xmss_h10", "lms": "lms_h10"}


def get_profile(name, hash_backend="shake"):
    if hash_backend != "shake":
        raise ValueError("unknown hash backend")
    if "omega" in name:
        raise ValueError("omega profiles were retired; use xmss_h10/h16/h20 or lms_h10/h15/h20")
    try:
        profile = PROFILES[ALIASES.get(name, name)]
    except KeyError:
        raise ValueError(f"unknown profile: {name}") from None
    return profile


def profile_names(hash_backend="shake", *, include_h20=True):
    if hash_backend != "shake": raise ValueError("unknown hash backend")
    return tuple(name for name in MICRO_NAMES
                 if (hash_backend == "shake" or get_profile(name).stateful or get_profile(name).n == 16)
                 and (include_h20 or not (get_profile(name).stateful and get_profile(name).h == 20)))

# Stable image codes: bits 1:0 select n, bit 2 selects the small-signature set.
SLH_PROFILE_CODES = {0:'slh_128f',1:'slh_192f',2:'slh_256f',
                     4:'slh_128s',5:'slh_192s',6:'slh_256s'}
SLH_NAMES = tuple(SLH_PROFILE_CODES.values())

STATEFUL_PROFILE_CODES = {8:"xmss_h10",9:"xmss_h16",10:"xmss_h20",11:"lms_h10",12:"lms_h15",13:"lms_h20"}
STATEFUL_NAMES = tuple(STATEFUL_PROFILE_CODES.values())
MICRO_NAMES = SLH_NAMES + STATEFUL_NAMES
