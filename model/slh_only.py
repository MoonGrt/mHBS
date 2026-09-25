"""Production SLH-only ABI 4 admission, independent of legacy seven-point images.

The historical interpreter remains available to reproduce archived evidence.
This module is the admission boundary for new SLH-only images and builds.
"""
from model.autonomous_hbs import AutonomousMachine, ProgramImage
from model.profiles import PROFILES
from model.unified_hbs import Kind, Shape, Source, field

SLH_PROFILES = {name: profile for name, profile in PROFILES.items()
                if profile.family == "slh"}
SLH_SHAPES = {Shape.ADDRESS_SEED, Shape.ADDRESS_VALUE,
              Shape.MESSAGE_PRF, Shape.MESSAGE_DIGEST, Shape.ADDRESS_LIST}


def admit(image: ProgramImage):
    """Validate every physical word, including unused descriptor entries."""
    logical, job, message = image.decode()
    profile = image.descriptors[1]
    if field(profile, 59, 1) or field(profile, 56, 3) != 1:
        raise ValueError("SLH-only profile required")
    if not any((logical.n, logical.hp, logical.a, logical.k, logical.m, logical.h)
               == (p.n, p.hp, p.a, p.k, p.m, p.h)
               for p in SLH_PROFILES.values()):
        raise ValueError("unsupported SLH profile")
    if logical.omega != 4 or job.q or image.program[40]:
        raise ValueError("SLH-only Job fields")
    for signing in (False, True):
        for command in logical.words(signing)[:-1]:
            if field(command, 76, 4) & 4:
                raise ValueError("SLH-only macro flags")
    for word in image.descriptors:
        kind = word >> 60
        if kind == Kind.HASH and field(word, 56, 4) not in SLH_SHAPES:
            raise ValueError("SLH-only recipe required")
        if kind == Kind.CHAIN and field(word, 20, 8) > 67:
            raise ValueError("SLH-only chain bound")
        if kind == Kind.TREE and (field(word, 36, 2) == 2 or
                                  field(word, 32, 2) == 2 or
                                  field(word, 29, 3)):
            raise ValueError("SLH-only tree mode")
        if kind == Kind.SEGMENT and field(word, 56, 4) in (Source.IDENTIFIER,
                                                            Source.INDEX):
            raise ValueError("SLH-only segment source")
    return logical, job, message


class SLHMachine(AutonomousMachine):
    def __init__(self, image: ProgramImage, observe=None):
        admit(image)
        super().__init__(image, observe)
