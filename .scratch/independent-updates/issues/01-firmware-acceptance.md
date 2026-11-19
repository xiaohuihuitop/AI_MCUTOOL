# 固件签名与备用板升级验收

Status: ready-for-human

COM40 已在候选期安装 0.1.4，保留给三路板上时序测试。1.0.0 配套发布的 0.1.4 烧录镜像与候选期相同。#8 的实板升级验收等待另一块运行较旧固件的备用板。取得备用板后，先核对端口、设备身份、板型、旧版本和允许重启的接线状态，再执行升级、重连并回读新版本。

固件使用独立 Ed25519 密钥，由 GitHub Actions 的 `firmware-release` 环境保管。该环境仅允许 `master` 分支。正式固件 0.1.4 已完成清单签名、包摘要与镜像版本核验，三路带载物理边沿的 ±5 ms 指标待实测。[Issue #8](https://github.com/xiaohuihuitop/AI_MCUTOOL/issues/8)
