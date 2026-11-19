/*
 * Base58 编码（Bitcoin 字母表）
 *
 * 揽号只编码 25 字节（21 字节 payload + 4 字节校验和），
 * 用「反复除以 58」得到 34～35 个字符；前导零字节按惯例换成 '1'。
 */

__constant uchar B58C[58] = {
    (uchar)'1', (uchar)'2', (uchar)'3', (uchar)'4', (uchar)'5',
    (uchar)'6', (uchar)'7', (uchar)'8', (uchar)'9',
    (uchar)'A', (uchar)'B', (uchar)'C', (uchar)'D', (uchar)'E',
    (uchar)'F', (uchar)'G', (uchar)'H', (uchar)'J', (uchar)'K',
    (uchar)'L', (uchar)'M', (uchar)'N', (uchar)'P', (uchar)'Q',
    (uchar)'R', (uchar)'S', (uchar)'T', (uchar)'U', (uchar)'V',
    (uchar)'W', (uchar)'X', (uchar)'Y', (uchar)'Z',
    (uchar)'a', (uchar)'b', (uchar)'c', (uchar)'d', (uchar)'e',
    (uchar)'f', (uchar)'g', (uchar)'h', (uchar)'i', (uchar)'j',
    (uchar)'k', (uchar)'m', (uchar)'n', (uchar)'o', (uchar)'p',
    (uchar)'q', (uchar)'r', (uchar)'s', (uchar)'t', (uchar)'u',
    (uchar)'v', (uchar)'w', (uchar)'x', (uchar)'y', (uchar)'z'
};

/*
 * 25 字节 → base58 字符串
 * 返回字符个数；out 至少 40 字节
 */
inline int base58_encode25(__private const uchar *in, __private uchar *out) {
    int z = 0;
    while (z < 25 && in[z] == 0) z++;

    /* 25 字节 → 7 个 32 位 limb（limb0 为最低 32 位） */
    uint n[7];
    for (int i = 0; i < 7; i++) {
        uint v = 0;
        for (int b = 0; b < 4; b++) {
            int pos = 24 - (i * 4 + b);
            if (pos >= 0) v |= ((uint)in[pos]) << (8 * b);
        }
        n[i] = v;
    }

    int top = 6;
    while (top >= 0 && n[top] == 0) top--;

    uchar digits[36];
    int nd = 0;
    while (top >= 0 && nd < 36) {
        ulong rem = 0;
        for (int i = top; i >= 0; i--) {
            ulong cur = (rem << 32) | (ulong)n[i];
            n[i] = (uint)(cur / 58u);
            rem = cur % 58u;
        }
        digits[nd++] = (uchar)rem;
        while (top >= 0 && n[top] == 0) top--;
    }

    int len = 0;
    for (int i = 0; i < z && len < 40; i++) out[len++] = (uchar)'1';
    for (int i = nd - 1; i >= 0 && len < 40; i--) out[len++] = B58C[digits[i]];
    return len;
}

/* 测试内核：in 每组 25 字节，out 每组 40 字节（第 0 字节为长度，后 36 字节为字符） */
__kernel void test_base58(__global const uchar *in, __global uchar *out) {
    int gid = get_global_id(0);
    uchar buf[25];
    uchar enc[40];
    for (int i = 0; i < 40; i++) enc[i] = 0;
    for (int i = 0; i < 25; i++) buf[i] = in[gid * 25 + i];
    int len = base58_encode25(buf, enc);
    out[gid * 40] = (uchar)len;
    for (int i = 0; i < 36; i++) out[gid * 40 + 1 + i] = enc[i];
}
