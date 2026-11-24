# Release v1.0.0 · 首次公开发布

## 这是什么

离线多链靓号地址生成器：私钥只在本机内存生成，软件无任何联网代码，断网可完整运行。

## 包含

- 8 条链：ETH / BSC / Polygon / Arbitrum / Base（EVM）、BTC / DOGE / TRON（Base58Check）
- CPU 多线程 + GPU（OpenCL）两条路径，GPU 默认关闭
- 前缀 / 后缀匹配，最多 32 条规则并行
- 批量生成，结果导出 `.xlsx`
- 授权码离线 Ed25519 验签，设备绑定
- 中英界面、规则记忆、开跑前确认框

## 验证

```bat
python app\main.py --selftest      :: 自检：生成 1 条地址
python tools\audit_no_network.py    :: 零联网审计，退出码 0
```

## 运行

- 源码：Python 3.9+（tkinter）、Node.js 18+，双击 `run.bat`
- Windows exe：见 Release 附件（解压即用，目标机器无需装 Python / Node）

## 安全承诺

- 不联网：无 socket / ssl / http / urllib / requests / webbrowser 引用
- 私钥不落盘：仅内存持有，导出 Excel 需手动确认
- 开源可审计：核心算法 MIT，任何人可自行跑审计脚本

## 已知边界

- GPU 目前仅适配 Windows；本地账本防手改但防不住专业逆向；不承诺绝对安全。
