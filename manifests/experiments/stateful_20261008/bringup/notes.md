# Bring-up 修正

- Keygen bench 最初误给 message_length=1，启动控制按契约拒绝；已改为 0。
- Verilator 的 $finish 后当前 initial 仍继续执行，故障检查后增加时钟等待，避免进入正常验证断言。
- XMSS omega4 截断测试最初等待固定 1000 拍，可能尚未完成前一批链；现先等待 verify_ready，再确认缺少节点时持续等待并执行复位恢复。
- 上述为测试驱动修正，不改变生产 RTL。最终证据按对应通过日志归档。
