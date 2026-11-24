# 推广文案（备用）

## V2EX（分享创造节点 · 中文）

标题：开源了一个离线多链靓号地址生成器，断网可跑、代码可审计

正文：
自己写的一个本地靓号地址生成工具，最近整理后开源了。

特点：
- 8 条链：ETH / BSC / Polygon / Arbitrum / Base、BTC / DOGE / TRON
- CPU 多线程 + GPU（OpenCL）两条路，GPU 默认关闭手动开
- 前缀 / 后缀匹配，最多 32 条规则同时跑，批量出结果导 Excel
- 最在意的一点：**软件没有任何联网代码**，私钥只在内存里，断网也能完整用；仓库里带一个审计脚本 `python tools/audit_no_network.py`，扫全部源码确认没有 socket / http / urllib / requests 这些引用，退出码 0 才算过。

不托管私钥、不做仿冒地址、不承诺安全。欢迎自己审代码。

仓库：https://github.com/wanminguo/vanity-generator

## Reddit（r/ethereum · 英文）

标题: Open-source offline vanity address generator — zero network code, auditable, CPU/GPU

Body:
I built a local vanity address generator and open-sourced it.

- Chains: ETH / BSC / Polygon / Arbitrum / Base (EVM), BTC / DOGE / TRON
- CPU threads or GPU (OpenCL, off by default)
- Prefix/suffix matching, up to 32 parallel rules, batch export to xlsx
- No networking code at all: private keys live in memory only, it runs fully offline. The repo includes `tools/audit_no_network.py` that scans every source file against socket/ssl/http/urllib/requests/webbrowser and exits 0 only when clean.

It never custodys keys, doesn't impersonate existing addresses, makes no "absolutely secure" claim. Code is MIT, audit it yourself.

https://github.com/wanminguo/vanity-generator

## X / Twitter（短）

Open-source offline vanity address generator (ETH/BTC/TRON, 8 chains).
Zero network code, keys in memory only, fully offline, CPU/GPU. Auditable, MIT.
https://github.com/wanminguo/vanity-generator

## 仓库元信息（网页右侧 About 齿轮里填）

- Description：离线多链靓号地址生成器（ETH/BSC/Polygon/Arbitrum/Base/BTC/DOGE/TRON）：零联网、可审计、CPU/GPU 并行。Offline vanity address generator, auditable, CPU/GPU.
- Website：https://buy.wanminguo.top/vanity/
- Topics：`ethereum` `vanity-address` `web3` `bitcoin` `tron` `crypto` `offline` `opencl` `secp256k1` `tkinter`
