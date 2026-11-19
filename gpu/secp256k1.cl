/*
 * secp256k1 有限域运算（8×32 位 limb，little-endian）
 *
 * p = 2^256 - 2^32 - 977
 * 归约利用 2^256 ≡ 2^32 + 977 (mod p)，把高位折叠回低位，最多几轮收敛。
 *
 * 只做加法链需要的操作：加、减、乘、平方、逆（Fermat）、倍加。
 * 不做标量乘 —— 揽号用「随机起点 + 逐步加 G」的增量方式，每步只要一次点加。
 */

#ifndef VG_TYPES_DEFINED
#define VG_TYPES_DEFINED
typedef unsigned long ulong;
typedef unsigned char uchar;
#endif

typedef uint u32;
typedef ulong u64;

typedef struct { u32 v[8]; } felem;

__constant u32 P[8] = {
    0xFFFFFC2Fu, 0xFFFFFFFEu, 0xFFFFFFFFu, 0xFFFFFFFFu,
    0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu
};

inline void fe_zero(felem *r) { for (int i = 0; i < 8; i++) r->v[i] = 0; }
inline void fe_one(felem *r) { fe_zero(r); r->v[0] = 1; }

inline int fe_is_zero(const felem *a) {
    u32 s = 0;
    for (int i = 0; i < 8; i++) s |= a->v[i];
    return s == 0;
}

inline int fe_gte_p(const felem *a) {
    for (int i = 7; i >= 0; i--) {
        if (a->v[i] > P[i]) return 1;
        if (a->v[i] < P[i]) return 0;
    }
    return 1;
}

/* 调用前必须保证 a >= p */
inline void fe_sub_p_once(felem *r) {
    u64 borrow = 0;
    for (int i = 0; i < 8; i++) {
        u64 d = (u64)r->v[i] - (u64)P[i] - borrow;
        r->v[i] = (u32)d;
        borrow = (d >> 32) & 1u;
    }
}

inline void fe_norm(felem *r) {
    for (int k = 0; k < 3; k++) {
        if (!fe_gte_p(r)) break;
        fe_sub_p_once(r);
    }
}

inline void fe_add(felem *r, const felem *a, const felem *b) {
    u64 c = 0;
    for (int i = 0; i < 8; i++) {
        u64 cur = (u64)a->v[i] + (u64)b->v[i] + c;
        r->v[i] = (u32)cur;
        c = cur >> 32;
    }
    if (c) {
        /* 溢出 2^256：加上 2^256 mod p = 0x1000003D1 */
        u64 cc = (u64)r->v[0] + 0x1000003D1ULL;
        r->v[0] = (u32)cc;
        cc >>= 32;
        int i = 1;
        while (cc && i < 8) {
            u64 t = (u64)r->v[i] + cc;
            r->v[i] = (u32)t;
            cc = t >> 32;
            i++;
        }
    }
    fe_norm(r);
}

inline void fe_sub(felem *r, const felem *a, const felem *b) {
    u64 borrow = 0;
    for (int i = 0; i < 8; i++) {
        u64 d = (u64)a->v[i] - (u64)b->v[i] - borrow;
        r->v[i] = (u32)d;
        borrow = (d >> 32) & 1u;
    }
    if (borrow) {
        u64 c = 0;
        for (int i = 0; i < 8; i++) {
            u64 cur = (u64)r->v[i] + (u64)P[i] + c;
            r->v[i] = (u32)cur;
            c = cur >> 32;
        }
    }
}

inline void fe_dbl(felem *r, const felem *a) { fe_add(r, a, a); }

/* 把 16 limb 的乘积归约到 8 limb */
inline void fe_reduce(felem *r, u32 *x) {
    for (int round = 0; round < 6; round++) {
        u32 hi = 0;
        for (int i = 8; i < 16; i++) hi |= x[i];
        if (!hi) break;

        u32 out[16];
        for (int i = 0; i < 16; i++) out[i] = 0;
        for (int i = 0; i < 8; i++) out[i] = x[i];

        for (int i = 0; i < 8; i++) {
            u64 h = (u64)x[8 + i];
            if (!h) continue;

            /* H[i] * 977 */
            u64 cur = (u64)out[i] + h * 977ULL;
            out[i] = (u32)cur;
            u64 c = cur >> 32;
            int k = i + 1;
            while (c && k < 16) {
                cur = (u64)out[k] + c;
                out[k] = (u32)cur;
                c = cur >> 32;
                k++;
            }

            /* H[i] << 32 */
            c = h;
            k = i + 1;
            while (c && k < 16) {
                cur = (u64)out[k] + c;
                out[k] = (u32)cur;
                c = cur >> 32;
                k++;
            }
        }

        for (int i = 0; i < 16; i++) x[i] = out[i];
    }

    for (int i = 0; i < 8; i++) r->v[i] = x[i];
    fe_norm(r);
}

inline void fe_mul(felem *r, const felem *a, const felem *b) {
    u32 x[16];
    for (int i = 0; i < 16; i++) x[i] = 0;

    for (int i = 0; i < 8; i++) {
        u64 carry = 0;
        u64 ai = (u64)a->v[i];
        for (int j = 0; j < 8; j++) {
            u64 cur = (u64)x[i + j] + ai * (u64)b->v[j] + carry;
            x[i + j] = (u32)cur;
            carry = cur >> 32;
        }
        int k = i + 8;
        while (carry && k < 16) {
            u64 cur = (u64)x[k] + carry;
            x[k] = (u32)cur;
            carry = cur >> 32;
            k++;
        }
    }

    fe_reduce(r, x);
}

inline void fe_sqr(felem *r, const felem *a) { fe_mul(r, a, a); }

/* a^(p-2)，Fermat 小定理；只在每批次做一次，成本可摊薄 */
inline void fe_inv(felem *r, const felem *a) {
    u32 e[8] = {
        0xFFFFFC2Du, 0xFFFFFFFEu, 0xFFFFFFFFu, 0xFFFFFFFFu,
        0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu
    };
    felem base = *a;
    fe_one(r);
    for (int i = 255; i >= 0; i--) {
        fe_sqr(r, r);
        if ((e[i >> 5] >> (i & 31)) & 1u) fe_mul(r, r, &base);
    }
}

/* ---------------- 测试入口（不参与揽号） ---------------- */

__kernel void test_mul(__global const u32 *a, __global const u32 *b, __global u32 *out) {
    int gid = get_global_id(0);
    felem x, y, z;
    for (int i = 0; i < 8; i++) { x.v[i] = a[gid * 8 + i]; y.v[i] = b[gid * 8 + i]; }
    fe_mul(&z, &x, &y);
    for (int i = 0; i < 8; i++) out[gid * 8 + i] = z.v[i];
}

__kernel void test_add(__global const u32 *a, __global const u32 *b, __global u32 *out) {
    int gid = get_global_id(0);
    felem x, y, z;
    for (int i = 0; i < 8; i++) { x.v[i] = a[gid * 8 + i]; y.v[i] = b[gid * 8 + i]; }
    fe_add(&z, &x, &y);
    for (int i = 0; i < 8; i++) out[gid * 8 + i] = z.v[i];
}

__kernel void test_sub(__global const u32 *a, __global const u32 *b, __global u32 *out) {
    int gid = get_global_id(0);
    felem x, y, z;
    for (int i = 0; i < 8; i++) { x.v[i] = a[gid * 8 + i]; y.v[i] = b[gid * 8 + i]; }
    fe_sub(&z, &x, &y);
    for (int i = 0; i < 8; i++) out[gid * 8 + i] = z.v[i];
}

__kernel void test_inv(__global const u32 *a, __global u32 *out) {
    int gid = get_global_id(0);
    felem x, z;
    for (int i = 0; i < 8; i++) x.v[i] = a[gid * 8 + i];
    fe_inv(&z, &x);
    for (int i = 0; i < 8; i++) out[gid * 8 + i] = z.v[i];
}
