# -*- coding: utf-8 -*-
"""Keccak-256 纯 Python 实现（仅用于 EIP-55 地址校验和与结果自检）

揽号本身在 GPU 内核里算哈希，这里只是在命中后把地址转成带校验和的写法。
不引入第三方库，不联网。
"""

MASK = (1 << 64) - 1

RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

ROTC = [1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 2, 14,
        27, 41, 56, 8, 25, 43, 62, 18, 39, 61, 20, 44]

PILN = [10, 7, 11, 17, 18, 3, 5, 16, 8, 21, 24, 4,
        15, 23, 19, 13, 12, 2, 20, 14, 22, 9, 6, 1]


def _rotl(x, n):
    return ((x << n) | (x >> (64 - n))) & MASK


def _keccakf(st):
    for rnd in range(24):
        bc = [st[i] ^ st[i + 5] ^ st[i + 10] ^ st[i + 15] ^ st[i + 20] for i in range(5)]
        for i in range(5):
            t = bc[(i + 4) % 5] ^ _rotl(bc[(i + 1) % 5], 1)
            for j in range(0, 25, 5):
                st[j + i] ^= t

        t = st[1]
        for i in range(24):
            j = PILN[i]
            tmp = st[j]
            st[j] = _rotl(t, ROTC[i])
            t = tmp

        for j in range(0, 25, 5):
            for i in range(5):
                bc[i] = st[j + i]
            for i in range(5):
                st[j + i] ^= ((~bc[(i + 1) % 5]) & MASK) & bc[(i + 2) % 5]

        st[0] ^= RC[rnd]
    return st


def keccak256(data: bytes) -> bytes:
    rate = 136
    st = [0] * 25

    msg = bytearray(data)
    msg.append(0x01)
    while len(msg) % rate != 0:
        msg.append(0x00)
    msg[-1] ^= 0x80

    for off in range(0, len(msg), rate):
        block = msg[off:off + rate]
        for i in range(rate // 8):
            st[i] ^= int.from_bytes(block[i * 8:(i + 1) * 8], "little")
        _keccakf(st)

    return b"".join(st[i].to_bytes(8, "little") for i in range(4))


def to_checksum(addr_hex: str) -> str:
    """EIP-55 校验和格式"""
    a = addr_hex.lower()
    if a.startswith("0x"):
        a = a[2:]
    h = keccak256(a.encode("ascii")).hex()
    out = []
    for i, ch in enumerate(a):
        if ch.isdigit():
            out.append(ch)
        else:
            out.append(ch.upper() if int(h[i], 16) >= 8 else ch)
    return "0x" + "".join(out)


if __name__ == "__main__":
    print(keccak256(b"").hex())
    print(keccak256(b"abc").hex())
    print(to_checksum("fb6916095ca1df60bb79ce92ce3ea74c37c5d359"))
