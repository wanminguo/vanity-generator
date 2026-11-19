/*
 * Keccak-256（以太坊variant，padding 0x01）—— OpenCL 版本
 *
 * 只处理「输入恰好 64 字节（公钥 x||y）」这一种情况，rate = 136 字节，
 * 一次吸收即可出结果，不实现通用消息长度处理。
 */

#ifndef VG_TYPES_DEFINED
#define VG_TYPES_DEFINED
typedef unsigned long ulong;
typedef unsigned char uchar;
#endif

__constant ulong RC[24] = {
    0x0000000000000001UL, 0x0000000000008082UL, 0x800000000000808aUL, 0x8000000080008000UL,
    0x000000000000808bUL, 0x0000000080000001UL, 0x8000000080008081UL, 0x8000000000008009UL,
    0x000000000000008aUL, 0x0000000000000088UL, 0x0000000080008009UL, 0x000000008000000aUL,
    0x000000008000808bUL, 0x800000000000008bUL, 0x8000000000008089UL, 0x8000000000008003UL,
    0x8000000000008002UL, 0x8000000000000080UL, 0x000000000000800aUL, 0x800000008000000aUL,
    0x8000000080008081UL, 0x8000000000008080UL, 0x0000000080000001UL, 0x8000000080008008UL,
};

__constant int ROTC[24] = {
    1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 2, 14,
    27, 41, 56, 8, 25, 43, 62, 18, 39, 61, 20, 44,
};

__constant int PILN[24] = {
    10, 7, 11, 17, 18, 3, 5, 16, 8, 21, 24, 4,
    15, 23, 19, 13, 12, 2, 20, 14, 22, 9, 6, 1,
};

#define ROTL64(x, n) (((x) << (n)) | ((x) >> (64 - (n))))

inline void keccakf(ulong *st) {
    ulong bc[5], t;
    for (int r = 0; r < 24; r++) {
        /* theta */
        for (int i = 0; i < 5; i++)
            bc[i] = st[i] ^ st[i + 5] ^ st[i + 10] ^ st[i + 15] ^ st[i + 20];
        for (int i = 0; i < 5; i++) {
            t = bc[(i + 4) % 5] ^ ROTL64(bc[(i + 1) % 5], 1);
            for (int j = 0; j < 25; j += 5) st[j + i] ^= t;
        }
        /* rho + pi */
        t = st[1];
        for (int i = 0; i < 24; i++) {
            int j = PILN[i];
            ulong tmp = st[j];
            st[j] = ROTL64(t, ROTC[i]);
            t = tmp;
        }
        /* chi */
        for (int j = 0; j < 25; j += 5) {
            for (int i = 0; i < 5; i++) bc[i] = st[j + i];
            for (int i = 0; i < 5; i++) st[j + i] ^= (~bc[(i + 1) % 5]) & bc[(i + 2) % 5];
        }
        /* iota */
        st[0] ^= RC[r];
    }
}

inline void keccak256_64(const uchar *in, uchar *out) {
    ulong st[25];
    for (int i = 0; i < 25; i++) st[i] = 0UL;

    for (int i = 0; i < 8; i++) {
        ulong v = 0UL;
        const uchar *p = in + i * 8;
        for (int b = 0; b < 8; b++) v |= ((ulong)p[b]) << (8 * b);
        st[i] = v;
    }
    st[8] ^= 0x01UL;                       /* domain separation（原始 Keccak） */
    st[16] ^= 0x8000000000000000UL;        /* 最后一个 rate 字节置 1（byte 135） */

    keccakf(st);

    for (int i = 0; i < 4; i++) {
        ulong v = st[i];
        uchar *p = out + i * 8;
        for (int b = 0; b < 8; b++) p[b] = (uchar)((v >> (8 * b)) & 0xFF);
    }
}

__kernel void keccak64(__global const uchar *in, __global uchar *out) {
    int gid = get_global_id(0);
    keccak256_64(in + gid * 64, out + gid * 32);
}
