# μHBS Job Interface v0.1

## 初始化接口

程序和 layout 只能在 `idle=1` 时写入；每幅镜像由 version、word count、entry table、resource bounds 和 SHA-256 digest 标识。开始 Job 后写使能必须被拒绝并置 `ERR_IMAGE_LOCKED`。

## 每操作唯一命令

逻辑 Job Descriptor：

```text
program_entry      u16
operation          u8   (KEYGEN=1, SIGN=2, VERIFY=3)
parameter_set      u16
message_base       u32
message_length     u32
secret_key_base    u32
public_key_base    u32
output_base        u32
state_handle       u32
flags              u16
```

描述符不含 task 序列、单次 Hash 输入、动态地址、树节点或 lane 决策。RTL 集成可将字段映射为寄存器或 DMA 请求，但语义保持一条原子 Job。

## 握手

- `job_valid && job_ready` 只允许在 IDLE 接受一次。
- 接受后 `job_ready=0`，直到 `done || error`。
- `done` 与 `error` 互斥，均为单次完成 token。
- 输出遵循 valid/ready；背压不允许主机注入控制信息。
- reset/cancel 进入清零流程；状态式索引按状态安全协议烧毁。

## 自主性计数器

验证构建暴露只读计数器：`accepted_job_commands`、`host_control_writes_during_busy`、`external_task_descriptors`、`external_hash_descriptors`。后两项在顶层接口中无输入端口，常量为零。
