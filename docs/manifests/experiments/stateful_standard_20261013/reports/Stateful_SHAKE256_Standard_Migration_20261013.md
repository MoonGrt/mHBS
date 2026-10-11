# SHAKE256 XMSS/LMS 六参数标准迁移（2026-10-13）

验收状态：用户已停止两组h=20全树运行，完整36项验收未完成。完整 RTL 三操作通过 30/36 项。未完成实测周期留空。运行时间预测独立记录于 [h=20预测报告](../h20_stopped/Stateful_h20_Runtime_Forecast_20261013.md)，不作为实测验收结果。

## 参数与接口

六组状态参数按 h 命名，固定32字节 SHAKE256输出、67条链。XMSS采用基数16；LMS采用RFC位数4。标准依据为 [SP 800-208](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-208.pdf)、[RFC 8391](https://www.rfc-editor.org/rfc/rfc8391.html) 和 [RFC 8554/9858](https://www.rfc-editor.org/rfc/rfc9858.html)。

| 参数 | h | 标准类型码 | 公钥字节 | 签名字节 |
|---|---:|---:|---:|---:|
| xmss_h10 | 10 | 0x10 | 68 | 2500 |
| xmss_h16 | 16 | 0x11 | 68 | 2692 |
| xmss_h20 | 20 | 0x12 | 68 | 2820 |
| lms_h10 | 10 | 0x10 | 56 | 2508 |
| lms_h15 | 15 | 0x11 | 56 | 2668 |
| lms_h20 | 20 | 0x12 | 56 | 2828 |

LM-OTS统一类型码0x0B；内部ROM配置码0x18～0x1D与标准类型码分离，旧omega名称及实验ROM码拒绝执行。TREE高度高位使用描述符bit39；程序/模板/描述符容量仍为16/16/32字。叶索引20位、遍历及LMS节点号21位、树层5位，栈与认证路径20层；端点与签名缓存容量保持原规模。

周期及Hash/置换统计全链路为64位，统计关闭时综合检查禁止残留统计寄存器。Keygen仅输出标准公钥，不输出密钥材料。Verify保留节点接口，由`hardware_verify_input`先检查标准公钥、签名长度、类型及q，再拆分节点。随机输入和q持久化仍由调用方提供；本次不宣称密码模块认证。

## 综合面积

同器件、通用Keccak映射、P4U1、统计关闭、OOC综合。top按Sign实例化，启用完整签名缓存，固定相应ROM、种子及根；common接受运行时Job/ROM，因此两者面积口径不同。等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。

| 综合顶层/参数 | LUT | FF | BRAM36等效 | 等效Slice |
|---|---:|---:|---:|---:|
| common | 33,889 | 10,797 | 0 | 9,821.875 |
| xmss_h10 | 29,486 | 10,459 | 11.5 | 11,351.475 |
| xmss_h16 | 31,221 | 10,520 | 11.5 | 11,792.850 |
| xmss_h20 | 30,264 | 10,468 | 11.5 | 11,547.100 |
| lms_h10 | 30,597 | 10,850 | 11.5 | 11,678.100 |
| lms_h15 | 31,275 | 10,856 | 11.5 | 11,848.350 |
| lms_h20 | 31,238 | 10,857 | 11.5 | 11,839.225 |

这些是综合面积，未进行本轮布局布线，不能据此宣称150 MHz闭合或实际STA频率下ATP改善。标准化与容量扩展后建立新基线，历史实验报告保留。

## 完整RTL实测

| 参数 | Keygen周期 | Sign周期 | Verify周期 |
|---|---:|---:|---:|
| xmss_h10 | 21,461,944 | 21,476,982 | 19,290 |
| xmss_h16 | 1,373,568,952 | 1,373,584,933 | 19,424 |
| xmss_h20 | 待完成 | 待完成 | 待完成 |
| lms_h10 | 7,333,891 | 7,340,300 | 6,678 |
| lms_h15 | 234,684,419 | 234,690,838 | 6,838 |
| lms_h20 | 待完成 | 待完成 | 待完成 |

全树运行逐拍执行生产RTL，检查每个输出字节、Sign缓存同步读回、实际Hash/置换完成事件及64位硬件统计。C++驱动不替换Keccak或控制器，也不外推周期。SystemVerilog测试台执行停顿、截断、复位重放、在途异常和兼容检查。

## 独立参考与验收证据

XMSS参考固定为`171ccbd26f098542a67eb5d2b128281c80bd71a6`；Cisco LMS参考固定为`cea4dda4f937e56ab42e1a74665f6397473a2838`。验证适配增加SHAKE256后端和RFC9858类型映射；XMSS参考的最后索引签名在使用密钥前清零，适配修正耗尽判断，使最后合法叶仍可签名。适配补丁、实际编译源码和校验单独归档。h10独立C与Python模型的公钥、签名及计数逐项匹配。

| 检查 | 状态 |
|---|---|
| full36 | 待完成 |
| recipes | 通过 |
| tags | 通过 |
| models | 通过 |
| common_synthesis | 通过 |
| top_synthesis | 通过 |
| edge_verify | 通过 |
| edge_reject | 通过 |
| compatibility | 通过 |
| single_slot_tail | 通过 |
| stats0 | 通过 |
| replay | 通过 |
| qmax_sign | 通过 |
| q1_sign | 通过 |
| retained_full30 | 通过 |
| slh_128f_fault_cut_tamper | 通过 |
| xmss_h10_fault_cut_tamper | 通过 |
| lms_h10_fault_cut_tamper | 通过 |
| old_rom_rejection | 通过 |
| frozen_source | 通过 |

重现入口：`python3 scripts/build_stateful_reference.py`、`python3 -m model.vectors`、`python3 scripts/check_standard_models.py`、`python3 -m scripts.validate_standard`、`scripts/validate_p4.sh`、`scripts/synth_top.tcl`、`python3 scripts/report_standard.py --require-complete`。
