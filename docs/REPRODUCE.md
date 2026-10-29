# 从自己的设备复现

AI 执行时先遵循 [SKILL.md](../SKILL.md) 的阶段规则，再使用本文命令。本文是操作参考，不代表可以跳过上一条的结果连续执行所有命令。

## 0. 匹配条件和文件

只连接一台目标设备。主板、固件版本、原始 OSLO 和 OBMI 哈希必须与 [设备事实卡](../facts/SUPPORTED_DEVICE.md) 及 `profile_ma217.py` 一致。任何已读到的值不同就停止套用，不能删掉断言继续刷。尚未取得的程序哈希按下文通过适用的只读路径补齐，不能预先猜测为匹配。脚本不能使用 `python -O`。

**不匹配时停止执行本文的型号专用命令，转入 [通用只读研究方法](RESEARCH_WORKFLOW.md)，继续识别、寻找提取入口和分析固件，不直接结束任务。** 本文的地址、协议编号和 noop 包都不能用于探测其他型号；本文件仅提供已验证组合的复现命令。

硬件操作需要可传文件的 USB 线、稳定装好的电池以及匹配的 WinUSB 驱动。全过程不使用 RESET、不清空 Flash、不改 IMEI / OTP / 未知 NV。

在 Windows PowerShell 中，从仓库根目录执行：

```powershell
git clone https://github.com/chenchen1010/ma217-mifi-unlock.git
cd ma217-mifi-unlock
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
New-Item -ItemType Directory -Force artifacts | Out-Null
gh release download v1.0.0 --repo chenchen1010/ma217-mifi-unlock --pattern '*.bin' --dir firmware
Get-FileHash firmware/OSLO-original.bin -Algorithm SHA256
Get-FileHash firmware/OSLO-unlocked.bin -Algorithm SHA256
```

没有 GitHub CLI 时，从 Release 页面手动下载同名附件到 `firmware/`。与 `SHA256SUMS.txt` 比较。不要把本机备份上传到 Issue。

## 1. 先辨认正常端口和网络出口

```powershell
Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -match 'VID_1286|VID_2ECC'}
Get-NetAdapter | Select-Object Name,ifIndex,Status
Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias,InterfaceIndex,IPAddress,AddressState
```

本例普通接口为 `1286:4E3D`，下载接口 `2ECC:3001` 只在开机早期出现。COM5 / COM6、接口索引 54 / 7 和 `.100` / `.199` 只是实机当时的分配，其他电脑必须重查。

USB 没出现不等于没有调试口。先检查电池、开机状态、数据线，再观察重启时的枚举。本机无需焊线、短接或移除屏蔽罩。

通过本地管理页或只读脚本取得版本。下面变量必须来自你的 MiFi 网络接口，不能用电脑原有网线的地址：

```powershell
$mifiIp = '192.168.1.100'  # 改成实际地址
$mifiIf = 54             # 改成实际接口索引
python mifi_probe.py --source-ip $mifiIp --only firmware_info mss_support_info status_info
```

默认账号密码使用该样机原标签的 `admin/admin`；若已修改，可通过当前进程的 `MIFI_USERNAME` / `MIFI_PASSWORD` 提供。不要把密码写进仓库。电脑原有路由器也可能是 `192.168.1.1`，因此联网脚本同时绑定源 IP 和 `IP_UNICAST_IF`，不走系统默认出口。

## 2. 下载口驱动与有限识别

驱动来自原 CATStudio 3.1.0.85 包中的 `Drivers/Drv/Win10/WTPTP_WinUSB.inf`。本例目录下 `WinUSB/wtptp_winusb_amd64.cat` 的签名是有效的 Microsoft Windows Hardware Compatibility Publisher。先核对签名，再在管理员 PowerShell 中使用 `pnputil /add-driver <完整 INF 路径> /install`。只安装驱动，不刷固件。

下载接口 GUID 为 `0C8AB63E-040C-428C-8050-1776087AD742`。参见 [来源](SOURCES.md) 的官方工具入口；不要把驱动安装包名含 1802S 当成硬件已确定为 1802S。

```powershell
python mifi_wtp_probe.py --probe --wait-seconds 120
```

脚本开始等待后，给设备正常重启或断电重新上电。看到灯亮就松开电源键，并保持电池、USB 稳定。查看生成的 `artifacts/wtp-probe-时间.json`：版本命令 `command=32`、`status=0`、payload 必须是 `313133331420010633415a4e`。

**这次识别调用了 GetVersion，会选择下载分支。识别结束后再次断电重启，不能直接把该会话接着用于 Flash Upload。** 退出时报 Disconnect 超时不等于需要发更多未知命令。

将刚才自己的 JSON 路径记为 `$probe`：

```powershell
$probe = 'artifacts/wtp-probe-你的时间.json'
```

## 3. 从小范围到两份 8 MiB 备份

每次先启动等待脚本，再触发一次正常重启或完整断电上电。回读采用新会话，Preamble → ProtocolVersion → Parameters → UploadHeader，**不调用 GetVersion**。

```powershell
python mifi_wtp_read_header.py --identification $probe --read-header --wait-seconds 180
```

确认生成 `.bin` 为 256 字节，配套 JSON 无 `error` 且 `bytes_read=256`，将该文件复制为 `artifacts/header.bin`。然后新一轮重启读取 TIM：

```powershell
python mifi_wtp_read_header.py --identification $probe --read-tim --wait-seconds 180
```

确认 3,920 字节，把这份 TIM 复制为 `artifacts/tim.bin`。脚本校验 header 和 TIM 的已验证哈希，避免依据猜测的布局继续扩大范围。

随后分别进行两次独立回读，每次都重新捕获启动口：

```powershell
python mifi_wtp_read_header.py --identification $probe --read-flash-8m --wait-seconds 180
```

保留两个不同时间的 `.bin` 和同名 `.json`。每次必须读满 8,388,608 字节并有一致的 SHA256。把路径记为 `$backup1`、`$backup2`。这里的 8 MiB 是实际读取范围，不是已证明的物理容量。曾读取 16 MiB 却得到两个相同的 8 MiB 半区，因此不能把容量通知当成独立全片证明。

部分退出时的 USB WinError 31 是设备切回正常接口；以 JSON 中是否读满、文件哈希和后续正常启动共同判断。如果有中途 `error` / `.partial`，不要用它作备份。

## 4. 离线生成自己的包

```powershell
python prepare_local.py --backup $backup1 --second-backup $backup2
python build_mifi_package.py --mode recover-original
python build_mifi_package.py --mode apply-rate-off
python build_mifi_package.py --mode noop
python -m unittest discover -s tests -v
python emulate_mifi_package.py --mode recover-original
python emulate_mifi_package.py --mode apply-rate-off
python emulate_mifi_package.py --mode noop
python emulate_mifi_lzma.py
```

`prepare_local.py` 校验两次读取的固件、身份区、WebUI 一致，以及原 OSLO / OBMI 和补丁哈希；它只在本地创建 `artifacts/`。本例 PSM 配置可能正常变化，所以不能要求整个运行数据区每次启动都一样。

构建后运行检查，涉及包的测试不能因文件缺失而 `skipped`；所有模拟必须通过。修改包、恢复包唯一写入范围为 `0x260000..0x320000`，长度 `0xc0000`，起点和长度均按 128 KiB 对齐。包里的其他镜像只用于原机校验，`erase_size=0`、`commands=2`。严禁改成 `Erase All Flash`。

若要从 6 字节补丁自行重建程序镜像，下载官方 [LZMA SDK 26.05](https://www.7-zip.org/sdk.html)，执行：

```powershell
python rebuild_firmware.py --lzma '你的SDK目录/bin/x64/lzma.exe' --output artifacts/rebuilt-oslo.bin
```

输出必须与发布版 SHA256 完全相同。脚本从原始程序解压 AP，仅修改三个已知指令，再以 `lzma.exe e ... -d20` 重压缩。只有单流解压、字节回验和原机解压器回验都通过才继续。

## 5. 先走一次零擦写流程

```powershell
python mifi_wtp_package.py --mode noop
python mifi_wtp_package.py --mode noop --execute --wait-seconds 180
```

第二条开始监听后再重启设备。检查结果 JSON 的 `transfer_completed=true`，且三阶段 TIMH / FBFD / OBMI 都完成。`noop` 的 Flash 写入和擦除范围为空；它仍会占用下载会话，完成后需要验证正常启动。

接着再次按第 3 节读出 8 MiB，记录路径 `$noopReadback`，执行：

```powershell
python verify_readback.py $noopReadback --variant original --noop-proof
```

必须确认固件和身份区原样。`--noop-proof` 将保存你自己设备的证明文件；不能拿本项目作者的报告替代。至此仍未修改固件。

## 6. 写入、回读、正常启动

```powershell
python mifi_wtp_package.py --mode apply-rate-off
python mifi_wtp_package.py --mode apply-rate-off --execute --wait-seconds 180
```

监听后正常重启，传输和擦写期间不要拔线或按住电源键。程序发送完 FBFD 后会等待平台 Busy / Ready，不能看到进度 100% 就立即断电。

实际完成要求 JSON `transfer_completed=true`、三阶段全部完成，并观察正常 USB / WiFi 恢复。然后再次独立回读 8 MiB，记为 `$patchedReadback`：

```powershell
python verify_readback.py $patchedReadback --variant modified
```

必须匹配预期修改版，槽外程序、身份区与 WebUI 保持原样。若不匹配，按 [恢复文档](RECOVERY.md) 处理，不盲目重复写入。回读匹配只说明字节正确，还需要下面的联网验收。

## 7. 保存外置卡并验证重启持久性

断电插好自备电信卡，再开机。首次使用原网页动作保存外置卡，slot 2、手动选卡模式 1：

```powershell
python mifi_select_external.py --source-ip $mifiIp --apply --probe-inserted-card
python verify_mifi_internet.py --source-ip $mifiIp --interface-index $mifiIf
python observe_sim_override.py --source-ip $mifiIp --interface-index $mifiIf --seconds 300
```

不要仅凭 `pc_valid=1` 或信号灯判断成功。必须同时满足活动 ICCID 与外置卡一致、运营商 `CHN TELECOM`、SIM 禁用标志 0、指定接口 DNS / TLS / HTTP 成功。WiFi 和 USB 是不同接口，分别验证；重新连接后 IP 可能变化。

之后记录 `status_info.run_seconds`，用原管理页“重启设备”或断电重启。重新连接后确认 uptime 归零，再执行上面只读联网与观察命令，**不要再次运行选卡命令**，否则无法证明重启持久性。观察期间保持设备连接，并记录人为操作。

测速可选，单次最多读取并丢弃 16 MiB，会消耗手机卡流量：

```powershell
python mifi_rate_probe.py --source-ip $mifiIp --interface-index $mifiIf --label after
```

该测试只验证一条下载路径；不用于宣称运营商峰值带宽或全部限速均已解除。
