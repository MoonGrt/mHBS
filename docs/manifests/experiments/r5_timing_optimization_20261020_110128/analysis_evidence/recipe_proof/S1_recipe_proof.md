# R5 后 recipe 切分说明

- `source_word` 的 list source 移除动态 256→64 选择，只取低64位。ADDRESS_LIST 前缀48/56/64字节，只有n=24在position48跨过前缀，当前拍实际使用的list字为slot1/index0；后续完整列表由list_window接管。保留仅有效输入字节检查，padding、完整列表和136字节末尾无效高字不触发断言。P1标量路径保持原语义。
- `awaiting_response` 记录尚未发布的完整结果，发布边沿立即移除；`complete/busy` 仍在消费时释放。逐槽断言与 `complete & ~held` 等价，优先级、发布和消费周期均不变，去掉held_tag→动态清位→下一tag编码→上下文RAM的组合反馈。

本地P12U1测试：459条recipe已通过；12组batch测试共96请求已通过，含捕获停顿、乱序、同拍补发和地址边界。全部结果由同一源码SHA绑定，详见JSON。未运行Vivado，实际收益待父任务测量。
