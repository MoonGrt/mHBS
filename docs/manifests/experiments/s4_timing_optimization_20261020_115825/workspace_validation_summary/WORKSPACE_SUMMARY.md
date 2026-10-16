# T3 共享工作区提交与转发专项

结果：**2/2 组通过**，P4U1、P12U1均检查实际冻结executor和value RAM。冻结源码清单 SHA256：`5e34070f534d800fce6b8ddf37e56599fe40dc7cc58cb3b05f731e4eee1146ec`；源码未变化：True。

每配置完成430次逻辑读、302次物理RAM读、105次read0转发、121次read1转发、2次复位边缘pending提交，以及33项地址译码检查。覆盖128个地址、背靠背写、同地址覆盖、奇偶相邻/127与126保护对、认证节点先写与树栈后写。独立scoreboard分别核对捕获后的逻辑可见值和下一边缘实际RAM落盘值，未将两者混为一拍。

复位测试在pending有效时拉高rst，确认commit_valid清零；重新选择被复位的读地址后，检查forwarding关闭时raw RAM仍保存刚刚落盘的数据。物理RAM写使能未门控rst。

初版隔离bench先后遇到Verilator procedural force只采样当前RHS、优化后别名net强制不一致，以及复位自动改变读地址等测试驱动问题；均通过修正驱动和选择实际地址解决，保留全部断言，未修改生产或冻结RTL。初始失败日志仅留build运行目录。

详细命令、逐组日志校验和覆盖计数见`WORKSPACE_VALIDATION.json`。未执行Vivado或h20完整树。
