# -*- coding: utf-8 -*-
"""最小 QR 码编码器 —— 只用标准库，不联网、不依赖第三方库。

只实现 Byte 模式 + 纠错等级 M，版本 1-10 自动选择（足够放下购买链接，
最长能放 216 字节）。实现依据 ISO/IEC 18004：

· 数据编码 → RS 纠错 → 分块交织 → 矩阵放置 → 8 种掩码择优 → 格式/版本信息

对外只有一个函数：
    matrix = make_matrix("https://...")
    返回 list[list[bool]]，True 为黑块。尺寸 = 4*版本+17。
"""

# 纠错等级 M 的分块表：版本 -> (每块纠错码字数, [(块数, 每块数据码字数), ...])
_RS_BLOCKS = {
    1: (10, [(1, 16)]),
    2: (16, [(1, 28)]),
    3: (26, [(1, 44)]),
    4: (18, [(2, 32)]),
    5: (24, [(2, 43)]),
    6: (16, [(4, 27)]),
    7: (18, [(4, 31)]),
    8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}

# 校正图案中心坐标
_ALIGN = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}

# 纠错等级 M 的格式信息标识位
_EC_BITS_M = 0


# ---------- GF(256) 与 RS

def _gf_mul(x, y):
    z = 0
    for i in range(8):
        if (y >> i) & 1:
            z ^= x << i
        # 本原多项式 0x11D
    for i in range(14, 7, -1):
        if (z >> i) & 1:
            z ^= 0x11D << (i - 8)
    return z & 0xFF


def _rs_generator(deg):
    """生成多项式 g(x) = (x - a^0)(x - a^1)...(x - a^(deg-1))"""
    g = [1]
    root = 1
    for _ in range(deg):
        nxt = [0] * (len(g) + 1)
        for i, coeff in enumerate(g):
            nxt[i] ^= coeff
            nxt[i + 1] ^= _gf_mul(coeff, root)
        g = nxt
        root = _gf_mul(root, 2)
    return g


def _rs_ecc(data, deg):
    gen = _rs_generator(deg)
    rem = [0] * deg
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(deg):
            rem[i] ^= _gf_mul(factor, gen[i + 1])
    return rem


# ---------- 掩码与罚分

def _mask_bit(mask, x, y):
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (x // 3 + y // 2) % 2 == 0
    if mask == 5:
        return x * y % 2 + x * y % 3 == 0
    if mask == 6:
        return (x * y % 2 + x * y % 3) % 2 == 0
    return ((x + y) % 2 + x * y % 3) % 2 == 0


def _penalty(m, size):
    score = 0
    # 规则 1：连续同色 5 个起
    for line in _lines(m, size):
        run = 1
        for i in range(1, size):
            if line[i] == line[i - 1]:
                run += 1
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
            else:
                run = 1
    # 规则 2：2x2 同色块
    for y in range(size - 1):
        for x in range(size - 1):
            a = m[y][x]
            if a == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                score += 3
    # 规则 3：像定位图案的 1:1:3:1:1
    for line in _lines(m, size):
        s = "".join("1" if v else "0" for v in line)
        score += (s.count("10111010000") + s.count("00001011101")) * 40
    # 规则 4：深色比例偏离 50%
    total = size * size
    dark = sum(1 for y in range(size) for x in range(size) if m[y][x])
    k = abs(dark * 20 - total * 10) // total
    score += k * 10
    return score


def _lines(m, size):
    for y in range(size):
        yield [m[y][x] for x in range(size)]
    for x in range(size):
        yield [m[y][x] for y in range(size)]


# ---------- 格式信息 / 版本信息

def _draw_format(m, size, mask):
    data = (_EC_BITS_M << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    bits = (data << 10 | rem) ^ 0x5412

    def bit(i):
        return bool((bits >> i) & 1)

    for i in range(6):
        m[i][8] = bit(i)          # 左侧竖排 6 位
    m[7][8] = bit(6)
    m[8][8] = bit(7)
    m[8][7] = bit(8)
    for i in range(9, 15):
        m[8][14 - i] = bit(i)     # 顶部横排 6 位

    for i in range(8):
        m[8][size - 1 - i] = bit(i)          # 右上横排 8 位
    for i in range(8, 15):
        m[size - 15 + i][8] = bit(i)         # 左下竖排 7 位
    m[size - 8][8] = True     # 固定深色模块


def _draw_version(m, size, version):
    if version < 7:
        return
    rem = version
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    bits = version << 12 | rem
    for i in range(18):
        b = bool((bits >> i) & 1)
        a = size - 11 + i % 3
        c = i // 3
        m[c][a] = b
        m[a][c] = b


# ---------- 主流程

def make_matrix(text, version=None):
    """把文本编成 QR 矩阵。返回 list[list[bool]]（True=黑）。"""
    raw = str(text).encode("utf-8")
    if not raw:
        raise ValueError("内容为空")

    if version is None:
        version = None
        for v in range(1, 11):
            _, groups = _RS_BLOCKS[v]
            data_cw = sum(cnt * per for cnt, per in groups)
            count_bits = 8 if v <= 9 else 16
            if 4 + count_bits + 8 * len(raw) <= data_cw * 8:
                version = v
                break
        if version is None:
            raise ValueError("内容过长：最多 216 字节")

    ec_len, groups = _RS_BLOCKS[version]
    data_cw = sum(cnt * per for cnt, per in groups)

    # 1) 数据码字
    bits = []

    def push(val, n):
        for i in range(n - 1, -1, -1):
            bits.append((val >> i) & 1)

    push(0b0100, 4)                                   # Byte 模式
    push(len(raw), 8 if version <= 9 else 16)
    for byte in raw:
        push(byte, 8)

    cap = data_cw * 8
    for _ in range(min(4, max(0, cap - len(bits)))):
        bits.append(0)
    while len(bits) % 8:
        bits.append(0)

    pad = (0xEC, 0x11)
    k = 0
    while len(bits) < cap:
        push(pad[k % 2], 8)
        k += 1

    codewords = []
    for i in range(0, len(bits), 8):
        byte = 0
        for b in bits[i:i + 8]:
            byte = (byte << 1) | b
        codewords.append(byte)

    # 2) 分块 + 纠错 + 交织
    blocks = []
    pos = 0
    for cnt, per in groups:
        for _ in range(cnt):
            blocks.append(codewords[pos:pos + per])
            pos += per
    eccs = [_rs_ecc(blk, ec_len) for blk in blocks]

    stream = []
    longest = max(len(b) for b in blocks)
    for i in range(longest):
        for blk in blocks:
            if i < len(blk):
                stream.append(blk[i])
    for i in range(ec_len):
        for ecc in eccs:
            stream.append(ecc[i])

    # 3) 矩阵骨架
    size = 17 + 4 * version
    m = [[None] * size for _ in range(size)]
    isf = [[False] * size for _ in range(size)]

    def setf(r, c, val):
        m[r][c] = val
        isf[r][c] = True

    for r0, c0 in ((0, 0), (0, size - 7), (size - 7, 0)):
        for dr in range(7):
            for dc in range(7):
                d = max(abs(dr - 3), abs(dc - 3))
                setf(r0 + dr, c0 + dc, d != 2)
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                rr, cc = r0 + dr, c0 + dc
                if 0 <= rr < size and 0 <= cc < size and not isf[rr][cc]:
                    setf(rr, cc, False)

    for i in range(8, size - 8):
        if not isf[6][i]:
            setf(6, i, i % 2 == 0)
        if not isf[i][6]:
            setf(i, 6, i % 2 == 0)

    centers = _ALIGN[version]
    n_ap = len(centers)
    for i in range(n_ap):
        for j in range(n_ap):
            if (i == 0 and j == 0) or (i == 0 and j == n_ap - 1) or (i == n_ap - 1 and j == 0):
                continue
            r, c = centers[i], centers[j]
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    setf(r + dr, c + dc, max(abs(dr), abs(dc)) != 1)

    # 先占位，掩码后再写真实格式位
    for i in range(9):
        if not isf[8][i]:
            setf(8, i, False)
        if not isf[i][8]:
            setf(i, 8, False)
    for i in range(8):
        if not isf[8][size - 8 + i]:
            setf(8, size - 8 + i, False)
    for i in range(7):
        if not isf[size - 7 + i][8]:
            setf(size - 7 + i, 8, False)

    # 固定深色模块必须先占位，否则数据的最后一位会被它顶掉
    setf(size - 8, 8, True)

    # 4) 放数据位：右两列一组，蛇形上下
    data_bits = []
    for cw in stream:
        for i in range(7, -1, -1):
            data_bits.append((cw >> i) & 1)

    idx = 0
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
                    m[y][x] = bool(data_bits[idx]) if idx < len(data_bits) else False
                    idx += 1
        right -= 2

    # 5) 8 种掩码择优
    best = None
    for mask in range(8):
        cand = [row[:] for row in m]
        for y in range(size):
            for x in range(size):
                if not isf[y][x] and _mask_bit(mask, x, y):
                    cand[y][x] = not cand[y][x]
        _draw_format(cand, size, mask)
        _draw_version(cand, size, version)
        score = _penalty(cand, size)
        if best is None or score < best[0]:
            best = (score, mask, cand)

    return best[2]


def to_ascii(m, quiet=2):
    """调试用：把矩阵打成字符画"""
    size = len(m)
    pad = "  " * quiet
    lines = []
    for _ in range(quiet):
        lines.append(pad)
    for row in m:
        lines.append(pad + "".join("██" if v else "  " for v in row))
    for _ in range(quiet):
        lines.append(pad)
    return "\n".join(lines)
