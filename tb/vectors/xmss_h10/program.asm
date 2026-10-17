000: MASK          d=FIXED, imm=1
001: HEIGHT        d=HT, imm=0
002: CURSOR_INIT
003: CHAIN_INIT
004: MASK          d=FIXED, imm=1
005: CHAIN         d=FULL, a=L0, b=CURSOR
006: STORE         d=0, a=4, b=CHAIN0, imm=0
007: CHAIN_NEXT    imm=1
008: BR            d=CHAIN_MORE, a=0, b=0, imm=5
009: REDUCE_INIT   d=LTREE
010: LOAD          d=9, a=0, b=REDUCE_LEFT, imm=0
011: BR            d=LTREE_PAIR, a=0, b=1, imm=36
012: LOAD          d=10, a=0, b=REDUCE_RIGHT, imm=0
013: ADRS          d=LTREE_CURSOR, a=0
014: HASH          d=4, a=L0
015: WAIT
016: NMOV          d=2, a=4
017: HASH          d=5, a=L0
018: WAIT
019: NMOV          d=6, a=4
020: XMSS_MASK     d=0
021: NMOV          d=9, a=4
022: HASH          d=6, a=L0
023: WAIT
024: NMOV          d=6, a=4
025: XMSS_MASK     d=1
026: NMOV          d=6, a=4
027: NMOV          d=4, a=9
028: HASH          d=10, a=L0
029: WAIT
030: STORE         d=0, a=4, b=REDUCE_OUT, imm=0
031: REDUCE_NEXT   d=INDEX
032: BR            d=LTREE_MORE, a=0, b=0, imm=10
033: REDUCE_NEXT   d=LTREE_LEVEL
034: BR            d=REDUCE_AGAIN, a=0, b=0, imm=10
035: JMP           imm=38
036: NMOV          d=4, a=9
037: JMP           imm=30
038: NODE_BEGIN    d=CURSOR, a=0, imm=0
039: BR            d=INDEX_ODD, a=0, b=1, imm=82
040: NMOV          d=10, a=4
041: LOAD          d=9, a=1, b=LEVEL, imm=0
042: NODE_PARENT
043: ADRS          d=HT_NODE, a=0
044: HASH          d=4, a=L0
045: WAIT
046: NMOV          d=2, a=4
047: HASH          d=5, a=L0
048: WAIT
049: NMOV          d=6, a=4
050: XMSS_MASK     d=0
051: NMOV          d=9, a=4
052: HASH          d=6, a=L0
053: WAIT
054: NMOV          d=6, a=4
055: XMSS_MASK     d=1
056: NMOV          d=6, a=4
057: NMOV          d=4, a=9
058: HASH          d=10, a=L0
059: BR            d=INDEX_ODD, a=0, b=1, imm=81
060: WAIT
061: NMOV          d=10, a=4
062: LOAD          d=9, a=1, b=LEVEL, imm=0
063: NODE_PARENT
064: ADRS          d=HT_NODE, a=0
065: HASH          d=4, a=L0
066: WAIT
067: NMOV          d=2, a=4
068: HASH          d=5, a=L0
069: WAIT
070: NMOV          d=6, a=4
071: XMSS_MASK     d=0
072: NMOV          d=9, a=4
073: HASH          d=6, a=L0
074: WAIT
075: NMOV          d=6, a=4
076: XMSS_MASK     d=1
077: NMOV          d=6, a=4
078: NMOV          d=4, a=9
079: HASH          d=10, a=L0
080: BR            d=INDEX_ODD, a=0, b=0, imm=60
081: WAIT
082: STORE         d=1, a=4, b=LEVEL, imm=0
083: CURSOR_NEXT   imm=1
084: BR            d=CURSOR_MORE, a=0, b=0, imm=3
085: EMIT          a=4
086: END
087: MASK          d=FIXED, imm=1
088: HASH          d=2, a=L0
089: WAIT
090: NMOV          d=0, a=4
091: EMIT          a=0
092: HASH          d=3, a=L0
093: WAIT
094: NMOV          d=2, a=4
095: DIGITS
096: TARGET        d=LEAF
097: HEIGHT        d=HT, imm=0
098: CURSOR_INIT
099: BR            d=TARGET_LEAF, a=0, b=0, imm=107
100: CHAIN_INIT
101: MASK          d=FIXED, imm=1
102: CHAIN         d=FULL, a=L0, b=CURSOR
103: STORE         d=0, a=4, b=CHAIN0, imm=0
104: CHAIN_NEXT    imm=1
105: BR            d=CHAIN_MORE, a=0, b=0, imm=102
106: JMP           imm=115
107: CHAIN_INIT
108: MASK          d=FIXED, imm=1
109: DIGIT_LOAD    d=L0
110: CHAIN         d=CAP_FULL, a=L0, b=CURSOR
111: EMIT          a=7
112: STORE         d=0, a=4, b=CHAIN0, imm=0
113: CHAIN_NEXT    imm=1
114: BR            d=CHAIN_MORE, a=0, b=0, imm=109
115: REDUCE_INIT   d=LTREE
116: LOAD          d=9, a=0, b=REDUCE_LEFT, imm=0
117: BR            d=LTREE_PAIR, a=0, b=1, imm=142
118: LOAD          d=10, a=0, b=REDUCE_RIGHT, imm=0
119: ADRS          d=LTREE_CURSOR, a=0
120: HASH          d=4, a=L0
121: WAIT
122: NMOV          d=2, a=4
123: HASH          d=5, a=L0
124: WAIT
125: NMOV          d=6, a=4
126: XMSS_MASK     d=0
127: NMOV          d=9, a=4
128: HASH          d=6, a=L0
129: WAIT
130: NMOV          d=6, a=4
131: XMSS_MASK     d=1
132: NMOV          d=6, a=4
133: NMOV          d=4, a=9
134: HASH          d=10, a=L0
135: WAIT
136: STORE         d=0, a=4, b=REDUCE_OUT, imm=0
137: REDUCE_NEXT   d=INDEX
138: BR            d=LTREE_MORE, a=0, b=0, imm=116
139: REDUCE_NEXT   d=LTREE_LEVEL
140: BR            d=REDUCE_AGAIN, a=0, b=0, imm=116
141: JMP           imm=144
142: NMOV          d=4, a=9
143: JMP           imm=136
144: NODE_BEGIN    d=CURSOR, a=0, imm=0
145: BR            d=AUTH_MATCH, a=0, b=1, imm=147
146: STORE         d=2, a=4, b=LEVEL, imm=0
147: BR            d=INDEX_ODD, a=0, b=1, imm=171
148: NMOV          d=10, a=4
149: LOAD          d=9, a=1, b=LEVEL, imm=0
150: NODE_PARENT
151: ADRS          d=HT_NODE, a=0
152: HASH          d=4, a=L0
153: WAIT
154: NMOV          d=2, a=4
155: HASH          d=5, a=L0
156: WAIT
157: NMOV          d=6, a=4
158: XMSS_MASK     d=0
159: NMOV          d=9, a=4
160: HASH          d=6, a=L0
161: WAIT
162: NMOV          d=6, a=4
163: XMSS_MASK     d=1
164: NMOV          d=6, a=4
165: NMOV          d=4, a=9
166: HASH          d=10, a=L0
167: WAIT
168: BR            d=AUTH_MATCH, a=0, b=1, imm=170
169: STORE         d=2, a=4, b=LEVEL, imm=0
170: BR            d=INDEX_ODD, a=0, b=0, imm=148
171: STORE         d=1, a=4, b=LEVEL, imm=0
172: CURSOR_NEXT   imm=1
173: BR            d=CURSOR_MORE, a=0, b=0, imm=99
174: LEVEL_INIT
175: LOAD          d=10, a=2, b=LEVEL, imm=0
176: EMIT          a=10
177: LEVEL_NEXT
178: BR            d=LEVEL_MORE, a=0, b=0, imm=175
179: END
180: MASK          d=FIXED, imm=1
181: INPUT         d=0
182: HASH          d=3, a=L0
183: WAIT
184: NMOV          d=2, a=4
185: DIGITS
186: HEIGHT        d=HT, imm=0
187: TARGET        d=LEAF
188: CHAIN_INIT
189: DIGIT_LOAD    d=L0
190: INPUT         d=4
191: CHAIN         d=SUFFIX, a=L0, b=LEAF
192: STORE         d=0, a=4, b=CHAIN0, imm=0
193: CHAIN_NEXT    imm=1
194: BR            d=CHAIN_MORE, a=0, b=0, imm=189
195: REDUCE_INIT   d=LTREE
196: LOAD          d=9, a=0, b=REDUCE_LEFT, imm=0
197: BR            d=LTREE_PAIR, a=0, b=1, imm=222
198: LOAD          d=10, a=0, b=REDUCE_RIGHT, imm=0
199: ADRS          d=LTREE_LEAF, a=0
200: HASH          d=4, a=L0
201: WAIT
202: NMOV          d=2, a=4
203: HASH          d=5, a=L0
204: WAIT
205: NMOV          d=6, a=4
206: XMSS_MASK     d=0
207: NMOV          d=9, a=4
208: HASH          d=6, a=L0
209: WAIT
210: NMOV          d=6, a=4
211: XMSS_MASK     d=1
212: NMOV          d=6, a=4
213: NMOV          d=4, a=9
214: HASH          d=10, a=L0
215: WAIT
216: STORE         d=0, a=4, b=REDUCE_OUT, imm=0
217: REDUCE_NEXT   d=INDEX
218: BR            d=LTREE_MORE, a=0, b=0, imm=196
219: REDUCE_NEXT   d=LTREE_LEVEL
220: BR            d=REDUCE_AGAIN, a=0, b=0, imm=196
221: JMP           imm=224
222: NMOV          d=4, a=9
223: JMP           imm=216
224: NODE_BEGIN    d=TARGET, a=0, imm=0
225: BR            d=INDEX_ODD, a=0, b=0, imm=228
226: INPUT         d=6
227: JMP           imm=230
228: NMOV          d=6, a=4
229: INPUT         d=4
230: NODE_PARENT
231: ADRS          d=HT_NODE, a=0
232: NMOV          d=9, a=4
233: NMOV          d=10, a=6
234: HASH          d=4, a=L0
235: WAIT
236: NMOV          d=2, a=4
237: HASH          d=5, a=L0
238: WAIT
239: NMOV          d=6, a=4
240: XMSS_MASK     d=0
241: NMOV          d=9, a=4
242: HASH          d=6, a=L0
243: WAIT
244: NMOV          d=6, a=4
245: XMSS_MASK     d=1
246: NMOV          d=6, a=4
247: NMOV          d=4, a=9
248: HASH          d=10, a=L0
249: WAIT
250: BR            d=LEVEL_MORE, a=0, b=0, imm=225
251: NMOV          d=2, a=4
252: ROOT_COMPARE
253: END
