#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
纯标准库实现的 Ed25519 签名校验（RFC 8032）。

为什么自己写：
  Python 标准库没有 Ed25519；而项目约束是「零第三方依赖」，
  不能为了验签去装 pynacl / cryptography。
  验签只做一次，几十毫秒的纯 Python 曲线运算完全可以接受。

只实现 verify —— 不实现 sign，签名私钥永远不在这份代码里。
"""

import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
I = pow(2, (P - 1) // 4, P)


def _inv(x):
    return pow(x, P - 2, P)


def _x_recover(y):
    xx = (y * y - 1) * _inv(D * y * y + 1)
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = (x * I) % P
    if x % 2 != 0:
        x = P - x
    return x


_BY = 4 * _inv(5) % P
_BX = _x_recover(_BY)
_BASE = (_BX, _BY, 1, _BX * _BY % P)


def _add(p1, p2):
    """扩展坐标下的点加"""
    x1, y1, z1, t1 = p1
    x2, y2, z2, t2 = p2
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = t1 * 2 * D * t2 % P
    d = z1 * 2 * z2 % P
    e = b - a
    f = d - c
    g = d + c
    h = b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(point, scalar):
    result = (0, 1, 1, 0)
    while scalar > 0:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _equal(p1, p2):
    x1, y1, z1, _ = p1
    x2, y2, z2, _ = p2
    return (x1 * z2 - x2 * z1) % P == 0 and (y1 * z2 - y2 * z1) % P == 0


def _decode_point(data):
    if len(data) != 32:
        raise ValueError("公钥/点编码必须是 32 字节")
    y = int.from_bytes(data, "little")
    sign = (y >> 255) & 1
    y &= (1 << 255) - 1
    if y >= P:
        raise ValueError("y 坐标越界")
    x = _x_recover(y)
    if (x & 1) != sign:
        x = P - x
    if (y * y - x * x - 1 - D * x * x * y * y) % P != 0:
        raise ValueError("点不在曲线上")
    return (x, y, 1, x * y % P)


def verify(signature, message, public_key):
    """返回 True/False。signature 64 字节，public_key 32 字节原始格式"""
    if len(signature) != 64 or len(public_key) != 32:
        return False
    try:
        a_point = _decode_point(public_key)
        r_point = _decode_point(signature[:32])
    except ValueError:
        return False

    s = int.from_bytes(signature[32:], "little")
    if s >= L:
        return False

    h = int.from_bytes(
        hashlib.sha512(signature[:32] + public_key + message).digest(), "little"
    ) % L

    return _equal(_mul(_BASE, s), _add(r_point, _mul(a_point, h)))


def public_key_from_hex(hex_str):
    raw = bytes.fromhex(hex_str)
    if len(raw) != 32:
        raise ValueError("公钥 hex 必须是 32 字节（64 个 hex 字符）")
    return raw
