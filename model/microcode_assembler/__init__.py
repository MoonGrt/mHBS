from .assembler import assemble_document, load_and_assemble
from .isa import Instruction, Opcode

__all__ = ["Instruction", "Opcode", "assemble_document", "load_and_assemble"]
