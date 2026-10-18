000: MASK          d=FIXED, imm=1
001: HEIGHT        d=HT, imm=0
002: TREE          d=HT, a=ROOT, b=NONE
003: EMIT          a=4
004: END
005: MASK          d=FIXED, imm=1
006: HASH          d=2, a=L0
007: WAIT
008: NMOV          d=0, a=4
009: EMIT          a=0
010: HASH          d=3, a=L0
011: WAIT
012: NMOV          d=2, a=4
013: DIGITS
014: TARGET        d=LEAF
015: HEIGHT        d=HT, imm=0
016: TREE          d=HT, a=SIGN, b=NONE
017: END
018: MASK          d=FIXED, imm=1
019: INPUT         d=0
020: HASH          d=3, a=L0
021: WAIT
022: NMOV          d=2, a=4
023: DIGITS
024: TARGET        d=LEAF
025: HEIGHT        d=HT, imm=0
026: TREE          d=HT, a=VERIFY, b=NONE
027: NMOV          d=2, a=4
028: ROOT_COMPARE
029: END
