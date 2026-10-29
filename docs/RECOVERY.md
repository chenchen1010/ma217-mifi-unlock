# 恢复与验收

AI 进入本节前应遵循 [SKILL.md](../SKILL.md) 的失败分支，并按 [设备事实卡](../facts/SUPPORTED_DEVICE.md) 确认本机与原始备份的归属；型号不匹配时不套用恢复包。

恢复包应在首次修改之前，使用自己的原始备份生成并验证。不能从别人的 8 MiB 整机 dump 恢复自己的身份与校准信息。

## 已准备好自己的原始备份时

`prepare_local.py` 后生成的 `artifacts/original-flash.bin` 和 `local-profile.json` 必须保持不变。恢复包仅还原曾修改的完整块范围，不清空其他区域：

```powershell
python build_mifi_package.py --mode recover-original
python emulate_mifi_package.py --mode recover-original
python mifi_wtp_package.py --mode recover-original
python mifi_wtp_package.py --mode recover-original --execute --wait-seconds 180
```

先启动监听，再给设备断电重新上电。USB 与电池都断开约 10 秒，装回电池、接线、按电源到灯亮就松开；不要按 RESET。写入期间保持接触稳定。

恢复模式允许在正常系统无法启动时使用，但仍要求本地原始备份、对应型号、包哈希和两种擦除块模拟通过。这个工具不是跨设备救砖包，不要把自己的备份套到另一台设备。

成功传输后，按照复现文档再次读回 8 MiB：

```powershell
python verify_readback.py 'artifacts/这次恢复后的回读.bin' --variant original
```

随后验证正常 USB / WiFi、网页版本和运行状态。`transfer_completed=true` 不是“已恢复正常启动”。如果只传了一部分、未发送 FBFD Done，不能宣称写入完成；如果已经开始擦写，中断后的状态必须通过回读判断。

## 不能正常启动时先查什么

1. 看重启早期是否仍出现 `2ECC:3001`。下载口可用说明还有这条恢复通路，不需要盲目短接。
2. 确认已经绑定对应 WinUSB 驱动。下载口和正常 RNDIS / AT 驱动是两回事。
3. 先回读，比较错误是“补丁内容不符”还是“相邻区域被擦掉”，保留证据。
4. 只恢复自己的已验证完整块包，写完再次回读并确认正常启动。

没有原始备份、bootloader 不匹配或下载口完全不可用时，本仓库不能给出已验证的恢复保证。不要通过去掉校验、整片擦除或套别人的校准数据来继续。

这不意味着结束排查：保留故障状态和已执行写入记录，按 [通用只读研究方法](RESEARCH_WORKFLOW.md) 继续接口识别、原始备份搜集、恢复协议及镜像分析；只执行有依据的读取，不向不匹配设备发送本例恢复包。

## 本次为什么既有“还原成功”又有“修改成功”

顺序是：原始备份 → 初版未对齐补丁损坏相邻段 → 完整块恢复原程序且回读一致 → 正确的认证 / 切卡补丁 → 追加限速补丁 → 回读与重启上网通过。

因此设备最后留下的是修改版；“还原成功”指过程中救回原程序的那个阶段，不是最后又把修改撤销了。原始 OSLO、原始本机备份和经过验证的恢复包都单独保留。
