/*
 * Base58 链（BTC / DOGE / TRON）揽号内核
 *
 * 与 EVM 版共用同一套椭圆曲线点运算（vanity.cl）和批量求逆，
 * 只是「公钥 → 地址」这一段不同：
 *
 *   BTC  : base58check( 0x00 || ripemd160(sha256(压缩公钥 33B)) )
 *   DOGE : base58check( 0x1e || ripemd160(sha256(压缩公钥 33B)) )
 *   TRON : base58check( 0x41 || keccak256(非压缩公钥 64B)[12:] )
 *
 * base58check 的校验和是「双 sha256 取前 4 字节」。
 *
 * mode: 0 = BTC, 1 = DOGE, 2 = TRON（TRON 走 keccak 分支）
 * ver : 版本字节（0x00 / 0x1e / 0x41）
 *
 * 命中输出（每 hit 40 字节）：[0] = 字符长度，[1..36] = base58 字符
 */

/* 多规则并行：与 vanity.cl 同一套规则表布局 */
#ifndef VG_MAX_RULES
#define VG_MAX_RULES 8
#endif
#ifndef VG_RULE_MAX
#define VG_RULE_MAX 40
#endif

__kernel void vanity_base58(
    __global const u32 *k0,
    int steps,
    __global const uchar *rules_pre,
    __global const uchar *rules_suf,
    __global const int *rules_plen,
    __global const int *rules_slen,
    int rule_count,
    __global volatile u32 *hit_count,
    __global u32 *hit_meta,
    __global uchar *hit_addr,
    int max_hits,
    int chunk_size,
    int mode,
    uchar ver
) {
    int wid = get_global_id(0);
    u32 k[8];
    for (int i = 0; i < 8; i++) k[i] = k0[wid * 8 + i];

    jpoint P;
    scalar_mul_base(&P, k);

    felem gx, gy;
    fe_from_const(&gx, GX);
    fe_from_const(&gy, GY);

    int nchunks = steps / chunk_size;

    for (int c = 0; c < nchunks; c++) {
        jpoint pts[VG_CHUNK];
        int step = (c * chunk_size) + 1;

        for (int i = 0; i < chunk_size; i++) {
            jac_add_affine(&P, &P, &gx, &gy);
            pts[i] = P;
        }

        felem zs[VG_CHUNK];
        felem prod[VG_CHUNK + 1];
        fe_one(&prod[0]);
        for (int i = 0; i < chunk_size; i++) {
            zs[i] = pts[i].z;
            fe_mul(&prod[i + 1], &prod[i], &zs[i]);
        }

        felem inv;
        fe_inv(&inv, &prod[chunk_size]);

        for (int i = chunk_size - 1; i >= 0; i--) {
            felem zi, zi2, zi3, ax, ay;
            fe_mul(&zi, &inv, &prod[i]);
            fe_mul(&inv, &inv, &zs[i]);

            fe_sqr(&zi2, &zi);
            fe_mul(&zi3, &zi2, &zi);
            fe_mul(&ax, &pts[i].x, &zi2);
            fe_mul(&ay, &pts[i].y, &zi3);

            uchar axb[32], ayb[32];
            fe_to_bytes(&ax, axb);
            fe_to_bytes(&ay, ayb);

            uchar hash20[20];

            if (mode == 2) {
                /* TRON：非压缩 64 字节公钥 → keccak256 → 后 20 字节 */
                uchar pub[64];
                for (int b = 0; b < 32; b++) { pub[b] = axb[b]; pub[32 + b] = ayb[b]; }
                uchar kd[32];
                keccak256_64(pub, kd);
                for (int b = 0; b < 20; b++) hash20[b] = kd[12 + b];
            } else {
                /* BTC / DOGE：压缩公钥 33 字节 → sha256 → ripemd160 */
                uchar cp[33];
                cp[0] = (uchar)(0x02u | ((uint)ayb[31] & 1u));
                for (int b = 0; b < 32; b++) cp[1 + b] = axb[b];
                uchar s1[32];
                sha256_short(cp, 33, s1);
                ripemd160_32(s1, hash20);
            }

            uchar payload[21];
            payload[0] = ver;
            for (int b = 0; b < 20; b++) payload[1 + b] = hash20[b];

            uchar d1[32], d2[32];
            sha256_short(payload, 21, d1);
            sha256_short(d1, 32, d2);

            uchar full[25];
            for (int b = 0; b < 21; b++) full[b] = payload[b];
            for (int b = 0; b < 4; b++) full[21 + b] = d2[b];

            uchar str[40];
            int alen = base58_encode25(full, str);

            /* 逐条规则比对，命中任意一条即记一条 */
            int hit_rule = -1;
            #pragma unroll 1
            for (int r = 0; r < rule_count; r++) {
                int rp = rules_plen[r];
                int rs = rules_slen[r];
                if (rp + rs > alen) continue;
                int ok = 1;
                #pragma unroll 1
                for (int j = 0; j < rp; j++) {
                    if (str[j] != rules_pre[r * VG_RULE_MAX + j]) { ok = 0; break; }
                }
                if (ok) {
                    #pragma unroll 1
                    for (int j = 0; j < rs; j++) {
                        if (str[alen - rs + j] != rules_suf[r * VG_RULE_MAX + j]) { ok = 0; break; }
                    }
                }
                if (ok) { hit_rule = r; break; }
            }

            if (hit_rule >= 0) {
                u32 idx = atomic_inc(hit_count);
                if (idx < (u32)max_hits) {
                    hit_meta[idx * 3] = (u32)wid;
                    hit_meta[idx * 3 + 1] = (u32)(step + i);
                    hit_meta[idx * 3 + 2] = (u32)hit_rule;
                    hit_addr[idx * 40] = (uchar)alen;
                    for (int b = 0; b < 36; b++) hit_addr[idx * 40 + 1 + b] = str[b];
                }
            }
        }
    }
}
