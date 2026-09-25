"""Fixed physical packing of the v4.1 ABI 4 logical image.

The logical image remains program 64x128, template 64x128, descriptor 128x64.
Packing is common to all profiles and never derives hardware from image bits.
"""
from dataclasses import dataclass
from pathlib import Path
from model.autonomous_hbs import ProgramImage

# Preserve the low addresses directly. Reuse twelve unused low physical slots
# for the contiguous EMIT segments at logical addresses 64..84.
DESCRIPTOR_LOGICAL = list(range(64))
for physical, logical in zip([39, *range(53, 64)], [*range(64, 72), 80, 81, 82, 84]):
    DESCRIPTOR_LOGICAL[physical] = logical
DESCRIPTOR_LOGICAL = tuple(DESCRIPTOR_LOGICAL)
DESCRIPTOR_PHYSICAL = {logical: physical for physical, logical in enumerate(DESCRIPTOR_LOGICAL)}

# (logical lsb, physical lsb, width). Coordinates are supplied by program.
TEMPLATE_FIELDS = ((124, 60, 4), (116, 52, 8), (108, 44, 8),
                   (107, 43, 1), (103, 40, 3), (76, 16, 24), (3, 15, 1))
LOGICAL_MASK = sum(((1 << width)-1) << logical for logical, _, width in TEMPLATE_FIELDS)
PHYSICAL_MASK = sum(((1 << width)-1) << physical for _, physical, width in TEMPLATE_FIELDS)


def pack_template(word):
    if word < 0 or word & ~LOGICAL_MASK:
        raise ValueError('template contains fields outside the physical format')
    return sum(((word >> logical) & ((1 << width)-1)) << physical
               for logical, physical, width in TEMPLATE_FIELDS)


def unpack_template(word):
    if word < 0 or word & ~PHYSICAL_MASK:
        raise ValueError('physical template reserved bits')
    return sum(((word >> physical) & ((1 << width)-1)) << logical
               for logical, physical, width in TEMPLATE_FIELDS)


def validate_serial_schedule(image):
    """Check the single outstanding macro/event contract before RTL use."""
    decoded, _, _ = image.decode()
    for token in decoded.tokens:
        kind = token >> 126
        if kind < 2 and (((token >> 72) & ((1 << 24)-1)) or
                         ((token >> 18) & ((1 << 24)-1))):
            raise ValueError('second macro coordinate/stride is unsupported')
        if kind == 2 and ((token >> 60) & ((1 << 24)-1)):
            raise ValueError('second macro loop delta is unsupported')
    for sign in (False, True):
        issued = 0
        for word in decoded.words(sign):
            if word >> 124 == 15:
                continue
            if ((word >> 107) & 1) != 1 or ((word >> 106) & 1):
                raise ValueError('single macro issue required')
            if ((word >> 100) & 63) or (word & 7) or not (word & 8):
                raise ValueError('only tracked event zero is supported')
            expected = int(issued != 0)
            if (word >> 116) & 255 != expected or (word >> 108) & 255 != expected:
                raise ValueError('macro completion must be consumed before reuse')
            issued += 1


@dataclass(frozen=True)
class PhysicalImage:
    program: tuple[int, ...]
    templates: tuple[int, ...]
    descriptors: tuple[int, ...]

    @classmethod
    def pack(cls, image):
        image.decode()
        if any(word for address, word in enumerate(image.descriptors)
               if address not in DESCRIPTOR_PHYSICAL):
            raise ValueError('descriptor address outside physical map')
        return cls(image.program, tuple(map(pack_template, image.templates)),
                   tuple(image.descriptors[address] for address in DESCRIPTOR_LOGICAL))

    def unpack(self):
        if any(len(words) != 64 for words in (self.program, self.templates, self.descriptors)):
            raise ValueError('physical ROM capacity')
        if any(w < 0 or w >= 1 << 64 for w in self.descriptors):
            raise ValueError('physical descriptor width')
        descriptors = [0]*128
        for address, word in zip(DESCRIPTOR_LOGICAL, self.descriptors):
            descriptors[address] = word
        image = ProgramImage(self.program, tuple(map(unpack_template, self.templates)), tuple(descriptors))
        image.decode()
        return image

    def write(self, directory):
        self.unpack()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for name, words, width in (('program', self.program, 32),
                                   ('template', self.templates, 16),
                                   ('descriptor', self.descriptors, 16)):
            (directory/(name+'.mem')).write_text(''.join(f'{w:0{width}x}\n' for w in words))

    @classmethod
    def read(cls, directory):
        directory = Path(directory)
        result = cls(*(tuple(int(x, 16) for x in (directory/(name+'.mem')).read_text().split())
                       for name in ('program', 'template', 'descriptor')))
        result.unpack()
        return result
