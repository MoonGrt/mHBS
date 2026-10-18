000: MASK          d=FIXED, imm=1
001: HEIGHT        d=HT, imm=0
002: TREE          d=HT, a=ROOT, b=NONE
003: EMIT          a=4
004: END
005: MASK          d=FIXED, imm=1
006: NMOV          d=0, a=14
007: EMIT          a=0
008: HASH          d=3, a=L0
009: WAIT
010: NMOV          d=2, a=4
011: DIGITS
012: TARGET        d=LEAF
013: HEIGHT        d=HT, imm=0
014: TREE          d=HT, a=SIGN, b=NONE
015: END
016: MASK          d=FIXED, imm=1
017: INPUT         d=0
018: HASH          d=3, a=L0
019: WAIT
020: NMOV          d=2, a=4
021: DIGITS
022: TARGET        d=LEAF
023: HEIGHT        d=HT, imm=0
024: TREE          d=HT, a=VERIFY, b=NONE
025: NMOV          d=2, a=4
026: ROOT_COMPARE
027: END
