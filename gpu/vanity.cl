/* ==================================================================
 * 椭圆曲线点运算 + 揽号内核
 *
 * 策略：每个 work-item 从随机私钥 k0 出发，用增量点加 P += G 走一串地址。
 *   - 不做完整标量乘（只在每个 work-item 开头做一次，成本摊薄到几十万次）
 *   - 每 CHUNK 步做一次 Montgomery 批量求逆（1 次逆换 CHUNK 个 affine 坐标）
 *   - 私钥 = k0 + offset，由 CPU 端算（Python 大整数），GPU 只负责算地址
 * ================================================================== */

#ifndef VG_CHUNK
#define VG_CHUNK 8
#endif

/* 多规则并行：最多 8 条规则，每条前缀/后缀最多 40 个字符位 */
#ifndef VG_MAX_RULES
#define VG_MAX_RULES 8
#endif
#ifndef VG_RULE_MAX
#define VG_RULE_MAX 40
#endif

typedef struct { felem x, y, z; } jpoint;

__constant u32 GX[8] = {
    0x16F81798u, 0x59F2815Bu, 0x2DCE28D9u, 0x029BFCDBu,
    0xCE870B07u, 0x55A06295u, 0xF9DCBBACu, 0x79BE667Eu
};
__constant u32 GY[8] = {
    0xFB10D4B8u, 0x9C47D08Fu, 0xA6855419u, 0xFD17B448u,
    0x0E1108A8u, 0x5DA4FBFCu, 0x26A3C465u, 0x483ADA77u
};

inline void fe_from_const(felem *r, const __constant u32 *src) {
    for (int i = 0; i < 8; i++) r->v[i] = src[i];
}

/* Jacobian 倍点 dbl-2009-l */
inline void jac_dbl(jpoint *r, const jpoint *p) {
    felem A, B, C, D, E, F, t, x3, y3, z3;

    fe_sqr(&A, &p->x);
    fe_sqr(&B, &p->y);
    fe_sqr(&C, &B);
    fe_add(&t, &p->x, &B);
    fe_sqr(&t, &t);
    fe_sub(&t, &t, &A);
    fe_sub(&t, &t, &C);
    fe_dbl(&D, &t);

    fe_dbl(&E, &A);
    fe_add(&E, &E, &A);      /* 3*A */

    fe_sqr(&F, &E);
    fe_sub(&x3, &F, &D);
    fe_sub(&x3, &x3, &D);

    fe_sub(&t, &D, &x3);
    fe_mul(&y3, &E, &t);
    t = C;                   /* 8*C，注意 C 本身已经是 B^2 */
    fe_dbl(&t, &t);
    fe_dbl(&t, &t);
    fe_dbl(&t, &t);
    fe_sub(&y3, &y3, &t);

    fe_mul(&z3, &p->y, &p->z);
    fe_dbl(&z3, &z3);

    r->x = x3; r->y = y3; r->z = z3;
}

/* Jacobian + affine（add-2007-bl），affine 点用常量 G */
inline void jac_add_affine(jpoint *r, const jpoint *p, const felem *gx, const felem *gy) {
    felem z1z1, u2, s2, h, hh, i, j, rr, v, x3, y3, z3, t;

    fe_sqr(&z1z1, &p->z);
    fe_mul(&u2, gx, &z1z1);
    fe_mul(&t, &p->z, &z1z1);      /* z1^3 */
    fe_mul(&s2, gy, &t);

    fe_sub(&h, &u2, &p->x);
    fe_sqr(&hh, &h);
    fe_dbl(&i, &hh);
    fe_dbl(&i, &i);                /* 4*hh */
    fe_mul(&j, &h, &i);

    fe_sub(&rr, &s2, &p->y);
    fe_dbl(&rr, &rr);
    fe_mul(&v, &p->x, &i);

    fe_sqr(&x3, &rr);
    fe_sub(&x3, &x3, &j);
    fe_sub(&x3, &x3, &v);
    fe_sub(&x3, &x3, &v);

    fe_sub(&t, &v, &x3);
    fe_mul(&y3, &rr, &t);
    fe_mul(&t, &p->y, &j);
    fe_dbl(&t, &t);
    fe_sub(&y3, &y3, &t);

    fe_add(&t, &p->z, &h);
    fe_sqr(&z3, &t);
    fe_sub(&z3, &z3, &z1z1);
    fe_sub(&z3, &z3, &hh);

    r->x = x3; r->y = y3; r->z = z3;
}

/* k * G，double-and-add，每个 work-item 每批只做一次 */
inline void scalar_mul_base(jpoint *r, const u32 *k) {
    felem gx, gy;
    fe_from_const(&gx, GX);
    fe_from_const(&gy, GY);

    jpoint acc;
    fe_zero(&acc.x); fe_zero(&acc.y); fe_zero(&acc.z);   /* 无穷远：z=0 */

    for (int bit = 255; bit >= 0; bit--) {
        if (acc.z.v[0] == 0 && acc.z.v[1] == 0) {
            /* 仍是无穷远，跳过倍点 */
        } else {
            jac_dbl(&acc, &acc);
        }
        if ((k[bit >> 5] >> (bit & 31)) & 1u) {
            if (acc.z.v[0] == 0 && acc.z.v[1] == 0) {
                acc.x = gx; acc.y = gy;
                fe_one(&acc.z);
            } else {
                jac_add_affine(&acc, &acc, &gx, &gy);
            }
        }
    }
    *r = acc;
}

/* felem -> 32 字节（大端，符合公钥字节序） */
inline void fe_to_bytes(const felem *a, uchar *out) {
    for (int i = 0; i < 8; i++) {
        u32 v = a->v[7 - i];
        out[i * 4 + 0] = (uchar)((v >> 24) & 0xFF);
        out[i * 4 + 1] = (uchar)((v >> 16) & 0xFF);
        out[i * 4 + 2] = (uchar)((v >> 8) & 0xFF);
        out[i * 4 + 3] = (uchar)(v & 0xFF);
    }
}

/*
 * 主内核（支持多规则并行）
 *
 * k0          : 每个 work-item 的起点私钥（8 limb = 256 bit）
 * steps       : 每个 work-item 走多少步（建议 CHUNK 的整数倍）
 * rules_pre   : 规则表前缀，第 r 条占 [r*VG_RULE_MAX, r*VG_RULE_MAX+len)
 * rules_suf   : 规则表后缀，同上
 * rules_plen  : 每条规则的前缀长度
 * rules_slen  : 每条规则的后缀长度
 * rule_count  : 生效规则条数（命中任意一条即记一条命中）
 * hit_count   : 命中总数（原子累加）
 * hit_meta    : 每条命中 [work_id, offset, rule_index]（offset 从 1 开始）
 * hit_addr    : 每条命中 20 字节地址
 */
__kernel void vanity_evm(
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
    int chunk_size
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

        /* Montgomery 批量求逆：prod[i] = z0*z1*...*z(i-1) */
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

            uchar pub[64];
            fe_to_bytes(&ax, pub);
            fe_to_bytes(&ay, pub + 32);

            uchar hash[32];
            keccak256_64(pub, hash);

            /* 地址 = hash 后 20 字节 */
            uchar hex[40];
            for (int b = 0; b < 20; b++) {
                uchar v = hash[12 + b];
                hex[b * 2] = (uchar)(v >> 4);
                hex[b * 2 + 1] = (uchar)(v & 0x0F);
            }

            /* 逐条规则比对，命中任意一条即记一条 */
            int hit_rule = -1;
            #pragma unroll 1
            for (int r = 0; r < rule_count; r++) {
                int rp = rules_plen[r];
                int rs = rules_slen[r];
                int ok = 1;
                #pragma unroll 1
                for (int j = 0; j < rp; j++) {
                    if (hex[j] != rules_pre[r * VG_RULE_MAX + j]) { ok = 0; break; }
                }
                if (ok) {
                    #pragma unroll 1
                    for (int j = 0; j < rs; j++) {
                        if (hex[40 - rs + j] != rules_suf[r * VG_RULE_MAX + j]) { ok = 0; break; }
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
                    for (int b = 0; b < 20; b++) hit_addr[idx * 20 + b] = hash[12 + b];
                }
            }
        }
    }
}

__kernel void test_point(__global const u32 *k, __global uchar *out) {
    int gid = get_global_id(0);
    jpoint p;
    scalar_mul_base(&p, &k[gid * 8]);
    felem zi, zi2, zi3, ax, ay;
    fe_inv(&zi, &p.z);
    fe_sqr(&zi2, &zi);
    fe_mul(&zi3, &zi2, &zi);
    fe_mul(&ax, &p.x, &zi2);
    fe_mul(&ay, &p.y, &zi3);
    uchar buf[64];
    fe_to_bytes(&ax, buf);
    fe_to_bytes(&ay, buf + 32);
    for (int i = 0; i < 64; i++) out[gid * 64 + i] = buf[i];
}
