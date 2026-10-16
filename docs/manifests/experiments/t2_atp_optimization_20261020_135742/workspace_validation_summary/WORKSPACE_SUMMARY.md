# U2 写回互斥与工作区专项

结果：3/3 组通过。冻结源码清单 SHA256：`f6b25ab4f0c5c0aa0ec9d077f401e9bcf6390812162f9e81c5210ac7937bab58`，源码未变：True。

Frozen U2 actual executor parallel write mux and original-priority debug oracle. Independent hand-planned write scoreboard covers every128 workspace address, authentication-priority/PUSH_STACK-next-edge collision, FORS leaf/parent, Ltree, direct/rolling, scalar P1, root, 67-node in-place waves and5 odd-tail copies,127/126 bank guard, reset while writing with no stale phase. Separate unchanged generic value DEPTH136 covers all136 addresses and135/134 tail parity. Does not replace cryptographic full Sign or throughput/STA validation; no Vivado, no h20 full tree, no production/frozen RTL modifications.

当前executor容量128，因此只测试合法127/126；135/134由同一冻结value.sv的独立DEPTH136实例覆盖，未向executor注入越界访问。所有写入由测试计划独立指定使能、地址、数据，原优先级oracle和onehot0断言同时保持开启。
