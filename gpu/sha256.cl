/*
 * SHA-256（单块版本）
 *
 * 揽号场景只需要「短消息一次压缩」：
 *   - sha256(33 字节压缩公钥)
 *   - sha256(21 字节 payload)，以及再 sha256 一次得到校验和
 * 两者长度都 ≤ 55 字节，padding 后恰好一块，无需多块循环。
 *
 * 类型统一用 uint / uchar，避免与 secp256k1.cl 的 u32 typedef 冲突。
 */

#ifndef VG_TYPES_DEFINED
#define VG_TYPES_DEFINED
typedef unsigned long ulong;
typedef unsigned char uchar;
#endif

__constant uint K256[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u,
    0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u,
    0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u,
    0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u,
    0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu,
    0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
    0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u,
    0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u,
    0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u,
    0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
    0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u,
    0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
    0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u,
    0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
    0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u,
    0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u
};

inline uint sha_rotr(uint x, uint n) {
    return (x >> n) | (x << (32 - n));
}

/* 压缩一个 64 字节块 */
inline void sha256_compress(uint *h, __private const uchar *p) {
    uint w[64];
    for (int i = 0; i < 16; i++) {
        w[i] = ((uint)p[i * 4] << 24) | ((uint)p[i * 4 + 1] << 16)
             | ((uint)p[i * 4 + 2] << 8) | (uint)p[i * 4 + 3];
    }
    for (int i = 16; i < 64; i++) {
        uint s0 = sha_rotr(w[i - 15], 7) ^ sha_rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
        uint s1 = sha_rotr(w[i - 2], 17) ^ sha_rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }

    uint a = h[0], b = h[1], c = h[2], d = h[3];
    uint e = h[4], f = h[5], g = h[6], hh = h[7];

    for (int i = 0; i < 64; i++) {
        uint S1 = sha_rotr(e, 6) ^ sha_rotr(e, 11) ^ sha_rotr(e, 25);
        uint ch = (e & f) ^ ((~e) & g);
        uint t1 = hh + S1 + ch + K256[i] + w[i];
        uint S0 = sha_rotr(a, 2) ^ sha_rotr(a, 13) ^ sha_rotr(a, 22);
        uint maj = (a & b) ^ (a & c) ^ (b & c);
        uint t2 = S0 + maj;
        hh = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

    h[0] += a; h[1] += b; h[2] += c; h[3] += d;
    h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
}

/* 输入 n 字节（n <= 55），输出 32 字节摘要 */
inline void sha256_short(__private const uchar *msg, int n, __private uchar *out) {
    uchar blk[64];
    for (int i = 0; i < n; i++) blk[i] = msg[i];
    blk[n] = 0x80;
    for (int i = n + 1; i < 56; i++) blk[i] = 0;
    ulong bits = ((ulong)n) << 3;
    for (int i = 0; i < 8; i++) blk[56 + i] = (uchar)((bits >> (56 - 8 * i)) & 0xFFu);

    uint h[8];
    h[0] = 0x6a09e667u; h[1] = 0xbb67ae85u; h[2] = 0x3c6ef372u; h[3] = 0xa54ff53au;
    h[4] = 0x510e527fu; h[5] = 0x9b05688cu; h[6] = 0x1f83d9abu; h[7] = 0x5be0cd19u;

    sha256_compress(h, blk);

    for (int i = 0; i < 8; i++) {
        out[i * 4]     = (uchar)(h[i] >> 24);
        out[i * 4 + 1] = (uchar)(h[i] >> 16);
        out[i * 4 + 2] = (uchar)(h[i] >> 8);
        out[i * 4 + 3] = (uchar)(h[i]);
    }
}

/* 测试内核：对 in 中每组 n 字节求摘要，n 固定为 33 */
__kernel void test_sha256(__global const uchar *in, __global uchar *out) {
    int gid = get_global_id(0);
    uchar msg[33];
    uchar digest[32];
    for (int i = 0; i < 33; i++) msg[i] = in[gid * 33 + i];
    sha256_short(msg, 33, digest);
    for (int i = 0; i < 32; i++) out[gid * 32 + i] = digest[i];
}

/* 测试内核：对 in 中每组 21 字节（payload）做双 SHA-256，取前 4 字节 */
__kernel void test_sha256d21(__global const uchar *in, __global uchar *out) {
    int gid = get_global_id(0);
    uchar msg[21];
    uchar d1[32], d2[32];
    for (int i = 0; i < 21; i++) msg[i] = in[gid * 21 + i];
    sha256_short(msg, 21, d1);
    sha256_short(d1, 32, d2);
    for (int i = 0; i < 32; i++) out[gid * 32 + i] = d2[i];
}
