000: LAYER_INIT    d=TOP
001: TREE          d=HT, a=ROOT, b=NONE
002: NMOV          d=3, a=4
003: EMIT          a=11
004: EMIT          a=12
005: EMIT          a=13
006: EMIT          a=3
007: EMIT          a=13
008: EMIT          a=3
009: END
010: MASK          d=FIXED, imm=1
011: HASH          d=2, a=L0
012: WAIT
013: NMOV          d=0, a=4
014: EMIT          a=0
015: HASH          d=3, a=L0
016: WAIT
017: PARSE
018: GROUP_INIT
019: TARGET        d=FORS
020: TREE          d=FORS, a=SIGN, b=NONE
021: STORE         d=0, a=4, b=GROUP, imm=0
022: GROUP_NEXT
023: BR            d=GROUP_MORE, a=0, b=0, imm=19
024: ADRS          d=FORS_LIST, a=0
025: MASK          d=FIXED, imm=1
026: HASH          d=11, a=L0
027: WAIT
028: NMOV          d=2, a=4
029: DIGITS
030: TARGET        d=LEAF
031: BR            d=FINAL_LAYER, a=0, b=0, imm=37
032: TREE          d=HT, a=SIGN, b=NONE
033: NMOV          d=2, a=4
034: TREE_NEXT
035: LAYER_NEXT
036: JMP           imm=29
037: TREE          d=HT, a=SIGN, b=TOP_SHORTCUT
038: END
039: INPUT         d=0
040: MASK          d=FIXED, imm=1
041: HASH          d=3, a=L0
042: WAIT
043: PARSE
044: GROUP_INIT
045: TARGET        d=FORS
046: TREE          d=FORS, a=VERIFY, b=NONE
047: STORE         d=0, a=4, b=GROUP, imm=0
048: GROUP_NEXT
049: BR            d=GROUP_MORE, a=0, b=0, imm=45
050: ADRS          d=FORS_LIST, a=0
051: MASK          d=FIXED, imm=1
052: HASH          d=11, a=L0
053: WAIT
054: NMOV          d=2, a=4
055: TARGET        d=LEAF
056: DIGITS
057: TREE          d=HT, a=VERIFY, b=NONE
058: NMOV          d=2, a=4
059: BR            d=FINAL_LAYER, a=0, b=0, imm=63
060: TREE_NEXT
061: LAYER_NEXT
062: JMP           imm=55
063: ROOT_COMPARE
064: END
