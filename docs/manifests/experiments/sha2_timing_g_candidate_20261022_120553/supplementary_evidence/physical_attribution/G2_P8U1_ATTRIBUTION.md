# G2 P8U1返回控制实际布线归因

SOURCE为`ab5d8af4567af69ef516e5451fa5785f048ed6d67cd601db9300e9dadf02aa0a`。P8U1在6.666ns约束下WNS−0.348ns，hold通过、全路由、DRC错误0。`compression/output_tag_reg[0]_rep__0`到`scalar_result_reg[370]/CE`的数据路径6.793ns，7级（含MUXF7）；逻辑1.253ns、布线5.540ns（81.556%）。源tag复制网扇出129，路径继续选择phase／iteration与scalar写使能。

这项证据支持将返回事件与scalar写控制本地化，并不表明仅增加算术流水即可消除问题。P4U1同源严格150MHz通过（WNS+0.094ns）只属于G2；新I组合必须以自己的冻结源、14点实际布线验收，不借用此成功或P8失败。

原始报告路径和SHA、完整路由／DRC及P4同源对照见JSON。此归因不启动硬件、不修改旧SOURCE或控制器。
