# 原始资料与各自作用

- [morluto/rea](https://github.com/morluto/rea)：本次 6.8.0 实际解析管理页 JavaScript、识别 FDIUtil 的 PE 容器；原始诊断流返回不支持格式。详见 [实际作用事实卡](../facts/REA_USAGE.md)。不是同型号固件源、提取器或本仓库复现的必需依赖。
- [域格 ASR Cat4 Windows 升级说明](https://docs.yuge-info.com/doku.php?id=asr:cat4:update_w)：普通端口、早期 WUKONG 下载口、官方驱动和 SWDownloader 入口。该页面向域格列出的模块；其恢复出厂 / AT 指令不能直接推定适用本机。
- [移远 CATStudio 官方下载](https://developer.quectel.com/en/wp-content/uploads/sites/2/2024/11/CATStudio_V3.1.0.85.zip)：本次使用的 3.1.0.85 工具包，内含 WTPTP WinUSB 驱动。匹配的是实际硬件 ID 和签名，不代表移远官方声明支持这台 MA217。完整工具包约 147 MB，不随本仓库再分发。
- [LZMA SDK 官方页](https://www.7-zip.org/sdk.html)：本次使用 26.05 的 x64 `lzma.exe`，`e input output -d20`。发布工具不夹带下载器或驱动安装程序。
- [ASR1803 主机下载协议参考](https://github.com/thanhsmail/NASA-TRACKING-A7677S/tree/4f6b8e6465a69445fdc8774eab84659d23c38106/tools/linux/FBFDownload/FBFDownloader_C)：交叉核对 WTPTP 命令、Upload 流程、FBF 结构。旧头文件缺少本机 QSPI subtype，最终以新版官方工具和实机结果为准。
- [emuikernel/OBM](https://github.com/emuikernel/OBM)：交叉参考旧版设备侧状态机，GetVersion 与 Upload 分支的差别。
- [Flymero/OB-MiFiManager](https://github.com/Flymero/OB-MiFiManager)：LBF1A 原网页 API 和选卡协议参考；它不是本机固件提取器或此次补丁。

官方 SWDownloader 5.0.0.2 的名称映射和反向映射共同给出 QSPI_FLASH=27；更新记录显示 ASR1803 的 QSPI 回读支持在较新版本加入。本机 subtype 10 返回错误，27 实际回读成功。该结论的适用范围是本例，不把所有 ASR 型号混为一类。

本机固件直接从用户自有设备提取，并未找到一个可以代替提取、且已验证精确匹配的厂家公开固件下载。也没有取得本版完整诊断数据库；最后成功不依赖先拿到它。
