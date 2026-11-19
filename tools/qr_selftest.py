# -*- coding: utf-8 -*-
"""QR 编码器自测：用一套独立的解码器把矩阵读回文本，再校验 RS 余数为 0。

编码器（qr_code.py）与解码器（本文件）走两条不同路径：
  · 编码器：数据 → 码字 → 交织 → 放位 → 掩码 → 择优
  · 解码器：读格式位 → 反掩码 → 按蛇形取位 → 反交织 → RS 校验 → 解出文本
只要任一步坐标/交织/掩码写错，RS 余数不为 0 或文本对不上，测试就会失败。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import qr_code as qr

RS = qr._RS_BLOCKS
ALIGN = qr._ALIGN


def gf_div_ok(block, ec_len):
    """Syndromes 全 0 = 这个块没有错"""
    ok = True
    root = 1
    for _ in range(ec_len):
        acc = 0
        for coeff in block:
            acc = qr._gf_mul(acc, root) ^ coeff
        if acc != 0:
            ok = False
        root = qr._gf_mul(root, 2)
    return ok


def function_map(version):
    size = 17 + 4 * version
    isf = [[False] * size for _ in range(size)]

    def mark(r, c):
        if 0 <= r < size and 0 <= c < size:
            isf[r][c] = True

    for r0, c0 in ((0, 0), (0, size - 7), (size - 7, 0)):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                mark(r0 + dr, c0 + dc)
    for i in range(size):
        mark(6, i)
        mark(i, 6)
    centers = ALIGN[version]
    n_ap = len(centers)
    for i in range(n_ap):
        for j in range(n_ap):
            if (i == 0 and j == 0) or (i == 0 and j == n_ap - 1) or (i == n_ap - 1 and j == 0):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    mark(centers[i] + dr, centers[j] + dc)
    for i in range(9):
        mark(8, i)
        mark(i, 8)
    for i in range(8):
        mark(8, size - 8 + i)
    for i in range(7):
        mark(size - 7 + i, 8)
    mark(size - 8, 8)     # 固定深色模块
    if version >= 7:
        for i in range(18):
            a = size - 11 + i % 3
            b = i // 3
            mark(b, a)
            mark(a, b)
    return isf


def bch_format(ec_bits, mask):
    data = ((ec_bits & 3) << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return (data << 10 | rem) ^ 0x5412


def read_format(m, size):
    """返回 (ec_bits, mask)，两份副本交叉验证"""
    first = []
    for i in range(6):
        first.append(m[i][8])
    first.append(m[7][8])
    first.append(m[8][8])
    first.append(m[8][7])
    for i in range(9, 15):
        first.append(m[8][14 - i])

    second = []
    for i in range(8):
        second.append(m[8][size - 1 - i])
    for i in range(8, 15):
        second.append(m[size - 15 + i][8])

    val1 = sum(1 << i for i, b in enumerate(first) if b)
    val2 = sum(1 << i for i, b in enumerate(second) if b)

    best = None
    for ec in range(4):
        for mask in range(8):
            want = bch_format(ec, mask)
            d = bin(val1 ^ want).count("1")
            if best is None or d < best[0]:
                best = (d, ec, mask)
    dist, ec, mask = best
    if dist > 3:
        raise AssertionError(f"格式信息不可纠（距离 {dist}）")
    want2 = bch_format(ec, mask)
    if bin(val2 ^ want2).count("1") > 3:
        raise AssertionError("第二份格式信息与第一份不一致")
    return ec, mask


def decode(m):
    size = len(m)
    version = (size - 17) // 4
    ec_bits, mask = read_format(m, size)

    isf = function_map(version)
    grid = [row[:] for row in m]
    for y in range(size):
        for x in range(size):
            if not isf[y][x] and qr._mask_bit(mask, x, y):
                grid[y][x] = not grid[y][x]

    ec_len, groups = RS[version]
    total = sum(cnt * per for cnt, per in groups) + ec_len * sum(cnt for cnt, _ in groups)

    bits = []
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = (size - 1 - vert) if upward else vert
                if not isf[y][x]:
                    bits.append(1 if grid[y][x] else 0)
        right -= 2

    if len(bits) < total * 8:
        raise AssertionError(f"数据位不足：{len(bits)} < {total * 8}")
    stream = []
    for i in range(total):
        byte = 0
        for b in bits[i * 8:(i + 1) * 8]:
            byte = (byte << 1) | b
        stream.append(byte)

    # 反交织
    lens = []
    for cnt, per in groups:
        lens.extend([per] * cnt)
    data_blocks = [[] for _ in lens]
    pos = 0
    longest = max(lens)
    for i in range(longest):
        for bi, per in enumerate(lens):
            if i < per:
                data_blocks[bi].append(stream[pos])
                pos += 1
    ecc_blocks = [[] for _ in lens]
    for i in range(ec_len):
        for bi in range(len(lens)):
            ecc_blocks[bi].append(stream[pos])
            pos += 1
    for bi in range(len(lens)):
        if not gf_div_ok(data_blocks[bi] + ecc_blocks[bi], ec_len):
            raise AssertionError(f"第 {bi + 1} 块 RS 校验失败（余数非 0）")

    # 解析 Byte 模式（按位流读，注意分块后数据块的顺序已由上面还原）
    allbits = []
    for bi, per in enumerate(lens):
        for byte in data_blocks[bi]:
            for k in range(7, -1, -1):
                allbits.append((byte >> k) & 1)

    def grab(n, at):
        v = 0
        for k in range(n):
            v = (v << 1) | allbits[at + k]
        return v, at + n

    mode, at = grab(4, 0)
    if mode != 0b0100:
        raise AssertionError(f"模式不是 Byte：{mode:04b}")
    count, at = grab(8 if version <= 9 else 16, at)
    out = []
    for _ in range(count):
        v, at = grab(8, at)
        out.append(v)
    return bytes(out).decode("utf-8"), ec_bits, mask, version


CASES = [
    "https://buy.wanminguo.top/vanity/?mid=VG-AE98-F034-B07D-7818",
    "https://buy.wanminguo.top/vanity/",
    "https://buy.wanminguo.top/vanity/?mid=VG-1111-2222-3333-4444&mail=a@b.c",
    "HELLO WORLD",
    "1234567890",
]


def main():
    ok = True
    for text in CASES:
        m = qr.make_matrix(text)
        size = len(m)
        version = (size - 17) // 4
        try:
            got, ec_bits, mask, v = decode(m)
        except AssertionError as exc:
            print(f"[FAIL] {text[:40]:<42} v{version} -> {exc}")
            ok = False
            continue
        if ec_bits != 0:
            print(f"[FAIL] {text[:40]:<42} 纠错等级不是 M（{ec_bits}）")
            ok = False
        elif got != text:
            print(f"[FAIL] {text[:40]:<42} 解出内容不一致：{got!r}")
            ok = False
        else:
            print(f"[ OK ] {text[:40]:<42} v{v} size={size} mask={mask}")
    print()
    print("结论：", "全部通过" if ok else "存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
