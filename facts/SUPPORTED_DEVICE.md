# 支持范围与事实来源

本卡是 AI 判断适用范围的入口。执行值以对应代码/发布清单为准，下面的链接用于定位；不得因模型记忆或相似教程覆盖它们。

## 唯一实机组合

| 检查项 | 预期与证据来源 |
|---|---|
| 主板 / `hardware_version` | `LBF1A_N10`；原网页 `firmware_info`，可用 PCB 丝印交叉核对 |
| 固件 / `version_num` | `LBF1ANT_N10_WH_2ESIM_V001`；[发布清单](../firmware/firmware-manifest.json) |
| 版本日期 | 本例 2025-08-18；日期文字不能替代程序哈希 |
| 平台 | ASR1803 / Falcon，本机 SDK 1.057.064；不能只根据驱动名称判断 |
| 正常 USB | `1286:4E3D`，RNDIS、AT、Diag |
| 启动 USB | `2ECC:3001`，WTPTP WinUSB；启动窗口曾只有约 1.87 秒 |
| bootloader | 版本 3311，已验证 payload 在 [回读器](../mifi_wtp_read_header.py) 中严格检查 |
| 头部 / TIM | 256 字节 / 3,920 字节；严格哈希在 [回读器](../mifi_wtp_read_header.py) 中 |
| 原程序 / bootloader 哈希 | [profile_ma217.py](../profile_ma217.py) 的 `ORIGINAL_OSLO_SHA`、`OBMI_SHA` |
| 修改程序哈希 / 补丁 | 同文件的 `MODIFIED_OSLO_SHA`、`PATCHES`；修改 AP 的 3 处、共 6 字节 |
| 实际写入范围 | 同文件的 `RECOVERY_OFFSET`、`RECOVERY_SIZE`：`0x260000..0x320000`，长度 `0xc0000` |
| 联网验收 | 自备中国电信 USIM，slot 2；其他运营商尚未验证 |

外壳标签 MA217 / 模组 MA216、屏蔽罩标签 ML358A-B-FMF 是本例线索，不足以单独判定其他设备兼容。没有必要为了收集非决定性标签而拆屏蔽罩或猜测焊盘。

## 不匹配和未知的区别

- 已取得的主板、固件、bootloader、头部、TIM 或原始程序哈希不同：该补丁为 `INCOMPATIBLE`，停止套用并继续 [通用只读研究](../docs/RESEARCH_WORKFLOW.md)，不能直接结束整个任务。
- 当前阶段还未取得后续阶段才可获得的值：`PENDING`，按已证实的只读路径补齐。例如原始 OSLO 哈希需要先完成相应回读。
- 接口、设备身份或文件来源无法确认：`UNKNOWN`，不猜、不进入写入；继续有依据的枚举、来源核对及离线分析。
- 已经刷过修改版：不能称为原始固件匹配。查找该设备此前的原始备份并先验证当前结果；不通过放宽原始哈希来重刷。

COM 号、Windows 接口索引、WiFi IP、SSID、IMEI、SIM 卡号和原始整机 SHA256 都是设备/会话相关值，必须本机读取。不得使用作者的示例值、原机整片 dump 或日志代替。

本卡约束的是现成 MA217 实现；研究其他型号时不能改掉这些值来消除不匹配。新型号需建立独立事实卡与实现，经过本机备份、布局/擦除语义和恢复验证后，才具备进入其写入流程的依据。

## 文件与容量

[公开固件清单](../firmware/firmware-manifest.json) 的两份文件是 4,259,840 字节 OSLO 应用镜像，原 Flash 范围为 `0x40000..0x450000`。其中 AP 压缩槽与实际完整块擦写范围不同。

完整备份指本次实读的 8 MiB 文件及其配套报告，不表示已独立证明整颗 Flash 的物理容量。曾读到的 16 MiB 前后半区相同，与地址回绕相符。不要把这些词混成“所有物理字节均已确认覆盖”。

## 历史验证与当前验收

[acceptance.json](../evidence/acceptance.json) 是作者这一台设备的历史结果；[reproduction-validation.json](../evidence/reproduction-validation.json) 是公开工具的离线验证。它们都不能替代当前新设备的回读和联网报告。

最终设备保留修改版，修复阶段的“原固件恢复成功”不代表最后撤销了补丁。最终追加限速补丁的五分钟观察被用户拔走中断，不能写成完整窗口通过。
