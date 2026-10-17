000: LAYER_INIT    d=TOP
001: HEIGHT        d=HT, imm=0
002: CURSOR_INIT
003: CHAIN_INIT
004: MASK          d=FIXED, imm=1
005: CHAIN         d=FULL, a=L0, b=CURSOR
006: STORE         d=0, a=4, b=CHAIN0, imm=0
007: CHAIN_NEXT    imm=1
008: BR            d=CHAIN_MORE, a=0, b=0, imm=5
009: ADRS          d=WOTS_LIST, a=0
010: MASK          d=FIXED, imm=1
011: HASH          d=9, a=L0
012: NODE_BEGIN    d=CURSOR, a=0, imm=0
013: WAIT
014: BR            d=INDEX_ODD, a=0, b=1, imm=22
015: NMOV          d=6, a=4
016: LOAD          d=4, a=1, b=LEVEL, imm=0
017: NODE_PARENT
018: ADRS          d=HT_NODE, a=0
019: HASH          d=10, a=L0
020: WAIT
021: BR            d=INDEX_ODD, a=0, b=0, imm=15
022: STORE         d=1, a=4, b=LEVEL, imm=0
023: CURSOR_NEXT   imm=1
024: BR            d=CURSOR_MORE, a=0, b=0, imm=3
025: NMOV          d=3, a=4
026: EMIT          a=11
027: EMIT          a=12
028: EMIT          a=13
029: EMIT          a=3
030: EMIT          a=13
031: EMIT          a=3
032: END
033: MASK          d=FIXED, imm=1
034: HASH          d=2, a=L0
035: WAIT
036: NMOV          d=0, a=4
037: EMIT          a=0
038: HASH          d=3, a=L0
039: WAIT
040: PARSE
041: GROUP_INIT
042: HEIGHT        d=FORS, imm=0
043: MASK          d=FIXED, imm=3
044: TARGET        d=FORS
045: CURSOR_INIT
046: JMP           imm=77
047: WAIT
048: NMOV          d=6, a=4
049: LOAD          d=4, a=1, b=LEVEL, imm=0
050: NODE_PARENT
051: ADRS          d=FORS_NODE, a=0
052: HASH          d=6, a=L0
053: JMP           imm=94
054: WAIT
055: STORE         d=2, a=4, b=LEVEL, imm=0
056: BR            d=INDEX_ODD, a=0, b=0, imm=48
057: JMP           imm=97
058: WAIT
059: NODE_BEGIN    d=TARGET, a=1, imm=0
060: BR            d=INDEX_ODD, a=0, b=0, imm=63
061: NMOV          d=7, a=4
062: JMP           imm=83
063: NMOV          d=7, a=5
064: JMP           imm=83
065: WAIT
066: BR            d=INDEX_ODD, a=0, b=0, imm=69
067: STORE         d=2, a=5, b=LEVEL, imm=0
068: JMP           imm=70
069: STORE         d=2, a=4, b=LEVEL, imm=0
070: CURSOR_NEXT   imm=1
071: NODE_BEGIN    d=CURSOR, a=1, imm=0
072: NODE_PARENT
073: ADRS          d=FORS_NODE, a=0
074: NMOV          d=6, a=5
075: HASH          d=6, a=L0
076: JMP           imm=94
077: ADRS          d=FORS_CURSOR, a=0
078: HASH          d=4, a=L0
079: WAIT
080: HASH          d=4, a=L1
081: BR            d=FORS_PAIR_TARGET, a=0, b=0, imm=58
082: WAIT
083: HASH          d=5, a=L0
084: WAIT
085: HASH          d=5, a=L1
086: BR            d=FORS_PAIR_TARGET, a=0, b=0, imm=65
087: CURSOR_NEXT   imm=1
088: NODE_BEGIN    d=CURSOR, a=1, imm=0
089: NODE_PARENT
090: ADRS          d=FORS_NODE, a=0
091: WAIT
092: NMOV          d=6, a=5
093: HASH          d=6, a=L0
094: BR            d=AUTH_MATCH, a=0, b=0, imm=54
095: BR            d=INDEX_ODD, a=0, b=0, imm=47
096: WAIT
097: STORE         d=1, a=4, b=LEVEL, imm=0
098: CURSOR_NEXT   imm=1
099: BR            d=CURSOR_MORE, a=0, b=0, imm=77
100: STORE         d=0, a=4, b=GROUP, imm=0
101: EMIT          a=7
102: LEVEL_INIT
103: LOAD          d=10, a=2, b=LEVEL, imm=0
104: EMIT          a=10
105: LEVEL_NEXT
106: BR            d=LEVEL_MORE, a=0, b=0, imm=103
107: GROUP_NEXT
108: BR            d=GROUP_MORE, a=0, b=0, imm=44
109: ADRS          d=FORS_LIST, a=0
110: MASK          d=FIXED, imm=1
111: HASH          d=11, a=L0
112: WAIT
113: NMOV          d=2, a=4
114: DIGITS
115: TARGET        d=LEAF
116: BR            d=FINAL_LAYER, a=0, b=0, imm=164
117: HEIGHT        d=HT, imm=0
118: CURSOR_INIT
119: BR            d=TARGET_LEAF, a=0, b=0, imm=127
120: CHAIN_INIT
121: MASK          d=FIXED, imm=1
122: CHAIN         d=FULL, a=L0, b=CURSOR
123: STORE         d=0, a=4, b=CHAIN0, imm=0
124: CHAIN_NEXT    imm=1
125: BR            d=CHAIN_MORE, a=0, b=0, imm=122
126: JMP           imm=135
127: CHAIN_INIT
128: MASK          d=FIXED, imm=1
129: DIGIT_LOAD    d=L0
130: CHAIN         d=CAP_FULL, a=L0, b=CURSOR
131: EMIT          a=7
132: STORE         d=0, a=4, b=CHAIN0, imm=0
133: CHAIN_NEXT    imm=1
134: BR            d=CHAIN_MORE, a=0, b=0, imm=129
135: ADRS          d=WOTS_LIST, a=0
136: MASK          d=FIXED, imm=1
137: HASH          d=9, a=L0
138: NODE_BEGIN    d=CURSOR, a=0, imm=0
139: WAIT
140: BR            d=AUTH_MATCH, a=0, b=1, imm=142
141: STORE         d=2, a=4, b=LEVEL, imm=0
142: BR            d=INDEX_ODD, a=0, b=1, imm=152
143: NMOV          d=6, a=4
144: LOAD          d=4, a=1, b=LEVEL, imm=0
145: NODE_PARENT
146: ADRS          d=HT_NODE, a=0
147: HASH          d=10, a=L0
148: WAIT
149: BR            d=AUTH_MATCH, a=0, b=1, imm=151
150: STORE         d=2, a=4, b=LEVEL, imm=0
151: BR            d=INDEX_ODD, a=0, b=0, imm=143
152: STORE         d=1, a=4, b=LEVEL, imm=0
153: CURSOR_NEXT   imm=1
154: BR            d=CURSOR_MORE, a=0, b=0, imm=119
155: LEVEL_INIT
156: LOAD          d=10, a=2, b=LEVEL, imm=0
157: EMIT          a=10
158: LEVEL_NEXT
159: BR            d=LEVEL_MORE, a=0, b=0, imm=156
160: NMOV          d=2, a=4
161: TREE_NEXT
162: LAYER_NEXT
163: JMP           imm=114
164: HEIGHT        d=HT, imm=0
165: CURSOR_INIT
166: BR            d=TARGET_LEAF, a=0, b=0, imm=174
167: CHAIN_INIT
168: MASK          d=FIXED, imm=1
169: CHAIN         d=FULL, a=L0, b=CURSOR
170: STORE         d=0, a=4, b=CHAIN0, imm=0
171: CHAIN_NEXT    imm=1
172: BR            d=CHAIN_MORE, a=0, b=0, imm=169
173: JMP           imm=183
174: CHAIN_INIT
175: MASK          d=FIXED, imm=1
176: DIGIT_LOAD    d=L0
177: CHAIN         d=CAP_PREFIX, a=L0, b=CURSOR
178: EMIT          a=7
179: CHAIN_NEXT    imm=1
180: BR            d=CHAIN_MORE, a=0, b=0, imm=176
181: NMOV          d=4, a=15
182: JMP           imm=187
183: ADRS          d=WOTS_LIST, a=0
184: MASK          d=FIXED, imm=1
185: HASH          d=9, a=L0
186: WAIT
187: NODE_BEGIN    d=CURSOR, a=0, imm=0
188: BR            d=AUTH_MATCH, a=0, b=1, imm=190
189: STORE         d=2, a=4, b=LEVEL, imm=0
190: BR            d=INDEX_ODD, a=0, b=1, imm=204
191: BR            d=SAME_PARENT, a=0, b=1, imm=195
192: NMOV          d=4, a=15
193: NODE_PARENT
194: JMP           imm=201
195: NMOV          d=6, a=4
196: LOAD          d=4, a=1, b=LEVEL, imm=0
197: NODE_PARENT
198: ADRS          d=HT_NODE, a=0
199: HASH          d=10, a=L0
200: WAIT
201: BR            d=AUTH_MATCH, a=0, b=1, imm=203
202: STORE         d=2, a=4, b=LEVEL, imm=0
203: BR            d=INDEX_ODD, a=0, b=0, imm=191
204: STORE         d=1, a=4, b=LEVEL, imm=0
205: CURSOR_NEXT   imm=1
206: BR            d=CURSOR_MORE, a=0, b=0, imm=166
207: LEVEL_INIT
208: LOAD          d=10, a=2, b=LEVEL, imm=0
209: EMIT          a=10
210: LEVEL_NEXT
211: BR            d=LEVEL_MORE, a=0, b=0, imm=208
212: END
213: INPUT         d=0
214: MASK          d=FIXED, imm=1
215: HASH          d=3, a=L0
216: WAIT
217: PARSE
218: HEIGHT        d=FORS, imm=0
219: GROUP_INIT
220: TARGET        d=FORS
221: INPUT         d=4
222: ADRS          d=FORS_TARGET, a=0
223: HASH          d=5, a=L0
224: NODE_BEGIN    d=TARGET, a=1, imm=0
225: WAIT
226: JMP           imm=228
227: WAIT
228: BR            d=INDEX_ODD, a=0, b=0, imm=231
229: INPUT         d=6
230: JMP           imm=233
231: NMOV          d=6, a=4
232: INPUT         d=4
233: NODE_PARENT
234: ADRS          d=FORS_NODE, a=0
235: HASH          d=6, a=L0
236: BR            d=LEVEL_MORE, a=0, b=0, imm=227
237: WAIT
238: STORE         d=0, a=4, b=GROUP, imm=0
239: GROUP_NEXT
240: BR            d=GROUP_MORE, a=0, b=0, imm=220
241: ADRS          d=FORS_LIST, a=0
242: HASH          d=11, a=L0
243: WAIT
244: NMOV          d=2, a=4
245: HEIGHT        d=HT, imm=0
246: TARGET        d=LEAF
247: DIGITS
248: CHAIN_INIT
249: DIGIT_LOAD    d=L0
250: INPUT         d=4
251: CHAIN         d=SUFFIX, a=L0, b=LEAF
252: STORE         d=0, a=4, b=CHAIN0, imm=0
253: CHAIN_NEXT    imm=1
254: BR            d=CHAIN_MORE, a=0, b=0, imm=249
255: ADRS          d=WOTS_LIST, a=1
256: HASH          d=9, a=L0
257: NODE_BEGIN    d=LEAF, a=0, imm=0
258: WAIT
259: JMP           imm=261
260: WAIT
261: BR            d=INDEX_ODD, a=0, b=0, imm=264
262: INPUT         d=6
263: JMP           imm=266
264: NMOV          d=6, a=4
265: INPUT         d=4
266: NODE_PARENT
267: ADRS          d=HT_NODE, a=0
268: HASH          d=10, a=L0
269: BR            d=LEVEL_MORE, a=0, b=0, imm=260
270: WAIT
271: NMOV          d=2, a=4
272: BR            d=FINAL_LAYER, a=0, b=0, imm=276
273: TREE_NEXT
274: LAYER_NEXT
275: JMP           imm=245
276: ROOT_COMPARE
277: END
