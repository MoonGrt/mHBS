000: MASK          d=FIXED, imm=1
001: HEIGHT        d=HT, imm=0
002: CURSOR_INIT
003: CHAIN_INIT
004: MASK          d=FIXED, imm=1
005: CHAIN         d=FULL, a=L0, b=CURSOR
006: STORE         d=0, a=4, b=CHAIN0, imm=0
007: CHAIN_NEXT    imm=1
008: BR            d=CHAIN_MORE, a=0, b=0, imm=5
009: ADRS          d=WOTS_LIST, a=0
010: HASH          d=9, a=L0
011: NODE_BEGIN    d=CURSOR, a=0, imm=0
012: ADRS          d=HT_NODE, a=0
013: WAIT
014: HASH          d=11, a=L0
015: NODE_BEGIN    d=CURSOR, a=0, imm=0
016: WAIT
017: BR            d=INDEX_ODD, a=0, b=1, imm=32
018: NMOV          d=6, a=4
019: LOAD          d=4, a=1, b=LEVEL, imm=0
020: NODE_PARENT
021: ADRS          d=HT_NODE, a=0
022: HASH          d=10, a=L0
023: BR            d=INDEX_ODD, a=0, b=1, imm=31
024: WAIT
025: NMOV          d=6, a=4
026: LOAD          d=4, a=1, b=LEVEL, imm=0
027: NODE_PARENT
028: ADRS          d=HT_NODE, a=0
029: HASH          d=10, a=L0
030: BR            d=INDEX_ODD, a=0, b=0, imm=24
031: WAIT
032: STORE         d=1, a=4, b=LEVEL, imm=0
033: CURSOR_NEXT   imm=1
034: BR            d=CURSOR_MORE, a=0, b=0, imm=3
035: EMIT          a=4
036: END
037: MASK          d=FIXED, imm=1
038: NMOV          d=0, a=14
039: EMIT          a=0
040: HASH          d=3, a=L0
041: WAIT
042: NMOV          d=2, a=4
043: DIGITS
044: TARGET        d=LEAF
045: HEIGHT        d=HT, imm=0
046: CURSOR_INIT
047: BR            d=TARGET_LEAF, a=0, b=0, imm=55
048: CHAIN_INIT
049: MASK          d=FIXED, imm=1
050: CHAIN         d=FULL, a=L0, b=CURSOR
051: STORE         d=0, a=4, b=CHAIN0, imm=0
052: CHAIN_NEXT    imm=1
053: BR            d=CHAIN_MORE, a=0, b=0, imm=50
054: JMP           imm=63
055: CHAIN_INIT
056: MASK          d=FIXED, imm=1
057: DIGIT_LOAD    d=L0
058: CHAIN         d=CAP_FULL, a=L0, b=CURSOR
059: EMIT          a=7
060: STORE         d=0, a=4, b=CHAIN0, imm=0
061: CHAIN_NEXT    imm=1
062: BR            d=CHAIN_MORE, a=0, b=0, imm=57
063: ADRS          d=WOTS_LIST, a=0
064: HASH          d=9, a=L0
065: NODE_BEGIN    d=CURSOR, a=0, imm=0
066: ADRS          d=HT_NODE, a=0
067: WAIT
068: HASH          d=11, a=L0
069: NODE_BEGIN    d=CURSOR, a=0, imm=0
070: WAIT
071: BR            d=AUTH_MATCH, a=0, b=1, imm=73
072: STORE         d=2, a=4, b=LEVEL, imm=0
073: BR            d=INDEX_ODD, a=0, b=1, imm=83
074: NMOV          d=6, a=4
075: LOAD          d=4, a=1, b=LEVEL, imm=0
076: NODE_PARENT
077: ADRS          d=HT_NODE, a=0
078: HASH          d=10, a=L0
079: WAIT
080: BR            d=AUTH_MATCH, a=0, b=1, imm=82
081: STORE         d=2, a=4, b=LEVEL, imm=0
082: BR            d=INDEX_ODD, a=0, b=0, imm=74
083: STORE         d=1, a=4, b=LEVEL, imm=0
084: CURSOR_NEXT   imm=1
085: BR            d=CURSOR_MORE, a=0, b=0, imm=47
086: LEVEL_INIT
087: LOAD          d=10, a=2, b=LEVEL, imm=0
088: EMIT          a=10
089: LEVEL_NEXT
090: BR            d=LEVEL_MORE, a=0, b=0, imm=87
091: END
092: MASK          d=FIXED, imm=1
093: INPUT         d=0
094: HASH          d=3, a=L0
095: WAIT
096: NMOV          d=2, a=4
097: DIGITS
098: HEIGHT        d=HT, imm=0
099: TARGET        d=LEAF
100: CHAIN_INIT
101: DIGIT_LOAD    d=L0
102: INPUT         d=4
103: CHAIN         d=SUFFIX, a=L0, b=LEAF
104: STORE         d=0, a=4, b=CHAIN0, imm=0
105: CHAIN_NEXT    imm=1
106: BR            d=CHAIN_MORE, a=0, b=0, imm=101
107: ADRS          d=WOTS_LIST, a=1
108: HASH          d=9, a=L0
109: NODE_BEGIN    d=TARGET, a=0, imm=0
110: ADRS          d=HT_NODE, a=0
111: WAIT
112: HASH          d=11, a=L0
113: NODE_BEGIN    d=TARGET, a=0, imm=0
114: WAIT
115: BR            d=INDEX_ODD, a=0, b=0, imm=118
116: INPUT         d=6
117: JMP           imm=120
118: NMOV          d=6, a=4
119: INPUT         d=4
120: NODE_PARENT
121: ADRS          d=HT_NODE, a=0
122: HASH          d=10, a=L0
123: WAIT
124: BR            d=LEVEL_MORE, a=0, b=0, imm=115
125: NMOV          d=2, a=4
126: ROOT_COMPARE
127: END
