#!/usr/bin/env python3
"""Archive the rejected TREE-free candidate and generate an evidence-bound report."""
import csv,difflib,hashlib,json,shutil,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'manifests/experiments/tree_microcode_20261003_v1'
WS=ROOT/'build/tree_microcode_20261003_v1'
SIM=WS/'build/v4.2/external_job_message/tree_free_v3'
BS=ROOT/'build/tree_microcode_area_baseline_20261003_v1/build/v4.2/external_job_message/tree_baseline_current'
DOC=ROOT/'docs/report/Tree_Microcode_Experiment.md'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_suffix('.tmp');temp.write_text(json.dumps(x,indent=2)+'\n');temp.replace(p)
def table(headers,rows):
 return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,r))+' |' for r in rows])+'\n'
def fmt(x):return f'{x:,.3f}' if isinstance(x,float) and not x.is_integer() else f'{int(x):,}'
software=read(OUT/'software/gate.json');sim=read(SIM/'simulation.json');baseline=read(BS/'simulation.json')
verify=read(SIM/'verify/results.json');bv=read(BS/'verify/results.json');extended=read(SIM/'extended.json');area=read(OUT/'area/result.json')
assert all(x['passed'] for x in (software,sim,baseline,verify,bv,extended)) and not verify['quick']
for v in ('baseline','candidate'):assert 'TREE_STEP_SYNTH_PASS' in (OUT/'area'/v/'driver.log').read_text()
names=list(verify['profiles']);cycles=[]
for name in names:
 for op,key in [('keygen','keygen_cycles'),('sign','sign_cycles'),('verify','cycles')]:
  a=sim['cases'][name+'_'+op] if op!='verify' else verify['profiles'][name]['normal']
  b=baseline['cases'][name+'_'+op] if op!='verify' else bv['profiles'][name]['normal']
  assert a['hashes']==b['hashes'] and a['permutations']==b['permutations']
  if op!='verify':assert a['output_sha256']==b['output_sha256']
  cycles.append(dict(profile=name,operation=op,baseline_cycles=b[key],candidate_cycles=a[key],increase_percent=100*(a[key]/b[key]-1),hashes=a['hashes'],permutations=a['permutations'],passed=a[key]*10<=b[key]*11))
# Preserve source-bound evidence, including output bytes, without retaining build binaries.
for variant,src in [('candidate',SIM),('baseline',BS)]:
 dest=OUT/'rtl'/variant;dest.mkdir(parents=True,exist_ok=True)
 for p in src.rglob('*'):
  if not p.is_file() or 'obj' in p.parts:continue
  if 'binaries' in p.parts and p.name!='compile.log':continue
  if p.suffix not in ('.log','.json','.mem','.gz','.sv','.v','.tcl'):continue
  q=dest/p.relative_to(src);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
for p in WS.glob('tree_*.log'):shutil.copy2(p,OUT/'rtl'/p.name)
# A full patch includes changed images and deletion of the old sequencer.
patch=[];changed=[]
with tarfile.open(OUT/'baseline/source_snapshot.tar.gz') as tar:
 for member in tar.getmembers():
  if not member.isfile():continue
  old=tar.extractfile(member).read();path=WS/member.name
  new=path.read_bytes() if path.exists() else b''
  if new==old:continue
  changed.append(dict(path=member.name,deleted=not path.exists(),baseline_sha256=hashlib.sha256(old).hexdigest(),candidate_sha256=hashlib.sha256(new).hexdigest() if path.exists() else None))
  try:patch.extend(difflib.unified_diff(old.decode().splitlines(True),new.decode().splitlines(True),fromfile='a/'+member.name,tofile='b/'+member.name if path.exists() else '/dev/null'))
  except UnicodeDecodeError:raise AssertionError('unexpected binary source')
(OUT/'candidate.patch').write_text(''.join(patch));write(OUT/'candidate_changes.json',changed)
# The signature-store instance is excluded only for the explicitly labelled core+ROM metric.
cache=dict(lut=485.,ff=293.,lutram=172.,bram36=11.5,dsp=0.,equivalent_slice=485/4+293/8+11.5*232.4)
for variant in area:
 area[variant]['core_rom']={}
 for name,total in area[variant]['profiles'].items():
  rows=[s for s in (OUT/'area'/variant/name/'hierarchical.rpt').read_text().splitlines() if 'stored_signature.storage' in s]
  assert len(rows)==1
  vals=[x.strip() for x in rows[0].split('|')[1:-1]]
  assert list(map(int,vals[2:]))==[485,313,172,0,293,11,1,0],vals
  area[variant]['core_rom'][name]={k:total[k]-cache[k] for k in cache}
production=read(OUT/'baseline/inputs.json')
changed_production=[p for p,h in production['source_sha256'].items() if not (ROOT/p).exists() or sha(ROOT/p)!=h]
assert not changed_production,changed_production
perf=all(r['passed'] for r in cycles)
area_pass=all(area['candidate']['core_rom'][n]['lut']<area['baseline']['core_rom'][n]['lut'] and area['candidate']['core_rom'][n]['equivalent_slice']<area['baseline']['core_rom'][n]['equivalent_slice'] and area['candidate']['core_rom'][n]['bram36']==0 for n in names)
result=dict(status='complete_rejected',adopted=False,software_gate=True,rtl_functional=True,cycle_gate=perf,area_gate=area_pass,production_unchanged=True,
 baseline_commit=(OUT/'baseline/commit.txt').read_text().strip(),rtl_normal_cases=18,rtl_extended_cases=len(extended['cases']),rtl_verify_cases=sum(len(x) for x in verify['profiles'].values()),cycles=cycles,area=area)
assert not perf and not area_pass
write(OUT/'result.json',result)
with (OUT/'cycles.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=cycles[0]);w.writeheader();w.writerows(cycles)
content='''# 用细粒度微码替代 TREE：实验结果

## 结论

**不采用本候选，生产 RTL 和原镜像保持不变。** 软件门禁、18 项正常 RTL 操作以及扩展回归通过，但周期和面积两个采用条件均失败。

- 六参数 Sign 周期增加 **10.0078%～42.2028%**；128s、192s Verify 也超过 10%。
- 共同核从 **21,043 LUT / 6252.250 等效 Slice** 增至 **24,112 LUT / 7004.875 等效 Slice**。
- 包含 program/template/descriptor ROM 后，六参数的总 LUT 和等效 Slice 均增加。
- 计算核及控制 ROM 没有新增 BRAM。完整顶层的签名缓存保留 11 BRAM36＋1 BRAM18。

这些数据只否定本次逐条执行的细粒度编码实现，不能推出所有无 TREE 微码方案都不划算。

## 基线与实验顺序

基线取实验开始时的当前源码，冻结于 `baseline/source_snapshot.tar.gz`；对应 Git 节点见 `baseline/commit.txt`，逐文件哈希见 `baseline/inputs.json`。本次新跑基线的六参数 Keygen/Sign/Verify，而非只引用旧周期。

1. 独立实现软件编码、编译器和解释器；软件门禁通过时核验生产 RTL 哈希未变。
2. `implement_candidate.py` 先校验通过标记及软件源文件哈希，再在 `build/tree_microcode_20261003_v1` 生成候选 RTL。
3. 对冻结的基线和候选分别仿真、共同核综合及六组 ROM/外壳综合；随后归档。
4. 门槛失败，不应用、不更新生产 ABI 指针；未布线、未测新频率、未提交或推送。

## 编码与实现

实验格式为 **slh_step_v5**：64 位字，`opcode[63:56] / a[55:48] / b[47:40] / c[39:32] / immediate[31:0]`。

保留 HASH、CHAIN、TRANSFORM、EMIT；增加 SET/MOV/ADD/ADDI、移位/掩码、比较分支、节点 LOAD/STORE/MOVN、INPUT/OUTPUT、HASH_PAIR、单返回槽 CALL/RET。编译器产生显式叶循环、栈读写、父坐标计算、单次父 Hash、认证路径收集和输出循环；Verify 显式输入并选择左右节点。没有 TREE 操作码或隐式递归归约。

- 六参数均使用 123 个有效字，容量向上取整到 **128 × 64 bit**，低于 256 字上限；同一程序覆盖三种操作。
- program：1024 B；template：128 B 占位零表；descriptor：256 B。每组逻辑镜像 **1408 B**，原版为 512 B。未使用的 template 在综合中可消除，面积表采用实测映射结果。
- 树栈、认证路径数组仍保留，各 16 × 256 bit，由显式指令寻址；沿用原节点端点存储与签名缓存，没有添加完整树缓存或新的 Hash 数据通路。
- CHAIN 只完成当前指定叶的 WOTS 链/端点归约或当前 FORS 成对叶，随后返回 FETCH。保留双 lane、WOTS 捕获、FORS 成对处理和末层外部根优化。
- 候选删除旧 sequencer 文件和 TREE_INIT/PUSH_NODE/PARENT_SETUP/AUTH_OUTPUT/TREE_FINISH 等状态；父 Hash 完成只返回微码，不隐式推进节点或回溯。
- 这是受编译器约束的实验 ISA；旧格式保留在基线，未在候选中提供兼容解码器，也未作为生产 ABI 发布。

## 软件门禁

六参数 × 4 组种子/消息（1、8、9、87 B）均完成 Keygen、Sign、正常 Verify。签名逐字节与独立算法参考比对；正常结果、根、长度、Hash/置换次数一致。地址包含在 Hash 输入中，使用完整输入及结果的顺序无关双重摘要核对 Hash 事件集合，允许独立任务重排；没有保存每条 Hash 的明文全量轨迹。

新解释器直接分派基础指令，不调用旧 `tree()` 或参考签名流程完成计算。HASH/CHAIN 复用基础 recipe/链实现，旧树和独立算法仅作对照；旧 TREE 执行入口在实验后端显式禁止。

通过 72 组受控树边界用例：首/尾叶、奇偶叶、多层归约、末 FORS group、WOTS 奇数链数、启用/禁用外部根优化。24 组完整签名各覆盖 R、FORS secret/auth、WOTS、XMSS auth、末尾 auth、消息篡改；额外拒绝旧格式、越界跳转、不终止循环、存储越界和错误签名长度。

### 动态指令数及节点存储占用

下表取基线种子、1 B 消息；`KG/SG/VF` 依次为三操作。栈/认证峰值是软件逻辑节点数，表示实际触及的槽位，不含 Python 对象开销、Hash 状态、端点存储、值寄存器和输出签名副本；这些硬件成本均计入后面的综合表。

'''
rows=[]
for n in names:
 s=software['profiles'][n]['1'];stats=[s[o] for o in ('keygen','sign','verify')]
 rows.append([n.removeprefix('slh_'),*(fmt(x['instructions']) for x in stats),'/'.join(str(x['peak_stack']) for x in stats),'/'.join(str(x['peak_auth']) for x in stats)])
content+=table(['参数','KG 指令','SG 指令','VF 指令','栈峰值 KG/SG/VF','认证峰值 KG/SG/VF'],rows)
content+='''
解释器还记录标量空间 64 B、五个节点暂存的逻辑字节数和各操作码执行次数。`schedule_lower_bound_cycles` 只计指令调度，**不是总周期预测**；Hash 等待、数据通路和状态转换由 RTL 实测。此粗估不足以保证 10% 门槛，实际采用判定以下表为准。

## RTL 周期与计算次数

相同向量、K2U2；正常操作不引入输入等待。周期为计算计数器口径，不含 boot。签名字节、输出顺序、输出长度及完整签名缓存读回通过；Hash/置换次数逐项与重新仿真的基线一致。

'''
content+=table(['参数/操作','基线周期','候选周期','增幅','Hash','置换','≤10%'],[[r['profile'].removeprefix('slh_')+' '+{'keygen':'KG','sign':'SG','verify':'VF'}[r['operation']],fmt(r['baseline_cycles']),fmt(r['candidate_cycles']),f"{r['increase_percent']:.4f}%",fmt(r['hashes']),fmt(r['permutations']),'通过' if r['passed'] else '**失败**'] for r in cycles])
content+=f'''
除正常 18 项外，扩展测试 **{len(extended['cases'])} 项**、完整 Verify **{sum(len(x) for x in verify['profiles'].values())} 项**通过（后者包含六项正常 Verify）：外部根传递、lane 交换、输入等待/尾部噪声、复位与重复执行、1/7/8/9/87 B 消息、统计关闭、共同核提取等价、故障退出，以及各种签名/公钥/消息篡改、节点填充和截断输入。

RTL 节点/父节点输入、输出来源及共享端点存储观察器随新 FETCH 流程更新。纯 Hash 单元未修改，本轮以集成回归覆盖其使用路径，没有重复单独跑全部原单元测试。恶意程序的跳转/存储/终止检查属于软件门禁，不宣称完成 RTL 对任意恶意微码的防护验证。

## 综合面积

Vivado 2025.2，xc7a200tffg1156-3，10 ns，8 线程，PROFILE_ENABLE=0，K2U2，DSP=0。共同核 OOC 综合后冻结网表；外壳使用实际三组控制镜像并独立综合，再链接同一共同核。基线和候选采用相同分区口径，禁止跨分区优化。完整顶层表指**链接后的综合面积**，没有物理优化或布线。

总 LUT 已含 LUTRAM，不能再次相加。等效 Slice 沿用项目公式：`LUT/4 + FF/8 + 232.4×BRAM36等效 + 102.4×DSP`；这是加权面积指标，不是已布局 Slice 数。

### 共同核

'''
keys=['lut','ff','lutram','bram36','dsp','equivalent_slice']
content+=table(['实现','总 LUT','FF','LUTRAM','BRAM36 等效','DSP','等效 Slice'],[[v,*[fmt(area[v]['core'][k]) for k in keys]] for v in ('baseline','candidate')])
content+='''
### 共同核＋program/template/descriptor ROM

从各参数完整顶层扣除相同签名缓存实例（485 LUT、293 FF、172 LUTRAM、11.5 BRAM36 等效），保留其余外壳连线开销，因此 ROM 开销是这个口径下的增量。

'''
content+=table(['参数','实现','总 LUT','FF','LUTRAM','BRAM36 等效','DSP','等效 Slice'],[[n.removeprefix('slh_'),v,*[fmt(area[v]['core_rom'][n][k]) for k in keys]] for n in names for v in ('baseline','candidate')])
content+='\n### 完整顶层（含同配置完整签名缓存）\n\n'
content+=table(['参数','实现','总 LUT','FF','LUTRAM','BRAM36 等效','DSP','等效 Slice'],[[n.removeprefix('slh_'),v,*[fmt(area[v]['profiles'][n][k]) for k in keys]] for n in names for v in ('baseline','candidate')])
content+='''
### 面积为何增加

分层报告显示：core 自身局部逻辑从 3761 LUT 增至 6368 LUT；删除旧 sequencer 节省 161 LUT，端点存储从 1868 减至 1808 LUT。两条 lane 的综合映射合计增加 683 LUT，Keccak 轮函数子模块仍各 2161 LUT。RTL Hash 源码未变，输入选择与控制可达性改变仍会改变整体映射；不能把全部增量归因于 ROM 容量。

本实现引入较宽的操作数选择、移位/算术、分支和微码可寻址节点路径；这些是面积增加的合理原因，但未做逐项消融以分离各因素。逐节点多条基础操作也增加了调度开销，尤其 FORS 树较深的 s 参数。Hash 工作量未增加，周期差额来自调度与数据移动。

## 采用判定与归档

功能通过；8/18 项正常操作周期超限；共同核及含 ROM 面积均变大。**不采用。** 生产源码、控制镜像和测试输入对照冻结清单逐项哈希一致；此次只增加实验脚本、证据和本报告。

证据根目录：[`manifests/experiments/tree_microcode_20261003_v1`](../../manifests/experiments/tree_microcode_20261003_v1)。删除 build 后仍保留：

- `baseline/`：源码快照、基线来源及历史记录；`rtl/baseline/`：本次重新仿真的基线。
- `software/gate.json`、`software/images/`：软件门禁、动态统计、新镜像和反汇编。
- `rtl/candidate/`：候选完整源码快照、18 项正常、扩展和 Verify 日志、实际输出、测试向量及编译日志。
- `candidate.patch`、`candidate_changes.json`：完整候选差异，含删除文件和镜像变化。
- `area/{baseline,candidate}/`：原始分层/资源报告、Tcl、源文件、网表、运行日志；网表可压缩保存。
- `result.json`、`cycles.csv`、`evidence.sha256`：最终判定、逐项周期与归档哈希。
- 实验脚本：[`experiments/tree_microcode_20261003_v1`](../../experiments/tree_microcode_20261003_v1)。运行顺序为 software_gate → implement_candidate → RTL 仿真 → synthesize → finalize；先恢复归档源码快照再重跑，不能将实验镜像直接用于生产 ABI。

初次链接因 EDIF 文件名与 top 名不匹配报错，随后修正文件名并成功重新链接；失败日志一并保留，不作为有效面积结果。最终外壳和共同核均使用 10 ns 综合约束。
'''
# Links are relative to docs/report, so reach repository root by two levels.
DOC.parent.mkdir(parents=True,exist_ok=True);DOC.write_text(content)
(OUT/'STATUS.md').write_text('# TREE 微码实验\n\n状态：**已结束，不采用**。\n\n软件门禁、RTL 功能与扩展回归通过；周期和面积门槛失败。生产源码及镜像未变，无运行任务需恢复。\n\n报告：`docs/report/Tree_Microcode_Experiment.md`\n结果：`result.json`\n')
# Compact netlists losslessly; keep every report directly readable.
for p in [*(OUT/'area').rglob('*.edf'),*(OUT/'baseline/synthesis').rglob('core_structure.txt')]:
 import gzip
 with p.open('rb') as src,gzip.open(str(p)+'.gz','wb') as dst:shutil.copyfileobj(src,dst)
 p.unlink()
# Save the exact experiment scripts alongside the source evidence.
shutil.copytree(Path(__file__).parent,OUT/'scripts',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name!='evidence.sha256' and '__pycache__' not in p.parts)
(OUT/'evidence.sha256').write_text(''.join(f'{sha(p)}  {p.relative_to(ROOT)}\n' for p in files)+f'{sha(DOC)}  {DOC.relative_to(ROOT)}\n')
print(json.dumps({k:result[k] for k in ('status','rtl_normal_cases','rtl_extended_cases','rtl_verify_cases','cycle_gate','area_gate','production_unchanged')},indent=2))
