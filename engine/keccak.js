/**
 * Keccak-256 —— 纯 JavaScript 实现（以太坊地址计算使用）
 *
 * 注意：以太坊用的是原始 Keccak（padding 0x01），不是 NIST SHA3-256（padding 0x06）。
 * 二者置换函数相同，仅 domain separation 字节不同，因此不能用 node:crypto 的 sha3-256 代替。
 *
 * 本文件不使用任何第三方库、不涉及任何网络能力。
 * 实现遵循 Keccak-f[1600] 规范：rate = 1088 bit（136 字节），输出 32 字节。
 */

// lane 状态用 32 位拆分存放：lane i 的低 32 位在 s[2i]，高 32 位在 s[2i+1]
const ROUND_COUNT = 24;

// 每轮常量 iota 的低/高 32 位
const RC_LO = [
  0x00000001, 0x00008082, 0x0000808a, 0x80008000, 0x0000808b, 0x80000001,
  0x80008081, 0x00008009, 0x0000008a, 0x00000088, 0x80008009, 0x8000000a,
  0x8000808b, 0x0000008b, 0x00008089, 0x00008003, 0x00008002, 0x00000080,
  0x0000800a, 0x8000000a, 0x80008081, 0x00008080, 0x80000001, 0x80008008,
];
const RC_HI = [
  0x00000000, 0x00000000, 0x80000000, 0x80000000, 0x00000000, 0x00000000,
  0x80000000, 0x80000000, 0x00000000, 0x00000000, 0x00000000, 0x00000000,
  0x00000000, 0x80000000, 0x80000000, 0x80000000, 0x80000000, 0x80000000,
  0x00000000, 0x80000000, 0x80000000, 0x80000000, 0x00000000, 0x80000000,
];

// ρ 旋转偏移，按 x*5+y 索引
const ROT = [
  0, 36, 3, 41, 18,
  1, 44, 10, 45, 2,
  62, 6, 43, 15, 61,
  28, 55, 25, 21, 56,
  27, 20, 39, 8, 14,
];

const RATE_BYTES = 136; // (1600 - 512) / 8
const RATE_WORDS = RATE_BYTES / 4; // 34 个 uint32

/**
 * Keccak-f[1600] 置换，就地修改 50 元素状态数组。
 * @param {Uint32Array} s 长度 50
 */
function keccakF1600(s) {
  const C = new Uint32Array(10);
  const D = new Uint32Array(10);
  const B = new Uint32Array(50);

  for (let round = 0; round < ROUND_COUNT; round++) {
    // ---- theta ----
    for (let x = 0; x < 5; x++) {
      let lo = 0;
      let hi = 0;
      for (let y = 0; y < 5; y++) {
        const i = 2 * (x + 5 * y);
        lo ^= s[i];
        hi ^= s[i + 1];
      }
      C[2 * x] = lo;
      C[2 * x + 1] = hi;
    }
    for (let x = 0; x < 5; x++) {
      const prev = ((x + 4) % 5) * 2;
      const next = ((x + 1) % 5) * 2;
      // rotl64(C[next], 1)
      const nl = C[next];
      const nh = C[next + 1];
      D[2 * x] = C[prev] ^ ((nl << 1) | (nh >>> 31));
      D[2 * x + 1] = C[prev + 1] ^ ((nh << 1) | (nl >>> 31));
    }
    for (let x = 0; x < 5; x++) {
      const dl = D[2 * x];
      const dh = D[2 * x + 1];
      for (let y = 0; y < 5; y++) {
        const i = 2 * (x + 5 * y);
        s[i] ^= dl;
        s[i + 1] ^= dh;
      }
    }

    // ---- rho + pi ----
    for (let x = 0; x < 5; x++) {
      for (let y = 0; y < 5; y++) {
        const src = 2 * (x + 5 * y);
        let lo = s[src];
        let hi = s[src + 1];
        const r = ROT[x * 5 + y];
        if (r === 32) {
          const t = lo;
          lo = hi;
          hi = t;
        } else if (r > 0 && r < 32) {
          const t = lo;
          lo = (lo << r) | (hi >>> (32 - r));
          hi = (hi << r) | (t >>> (32 - r));
        } else if (r > 32) {
          const m = r - 32;
          const tLo = lo;
          const tHi = hi;
          lo = (tHi << m) | (tLo >>> (32 - m));
          hi = (tLo << m) | (tHi >>> (32 - m));
        }
        // B[y, 2x+3y] = rot(A[x, y])
        const dst = 2 * (y + 5 * ((2 * x + 3 * y) % 5));
        B[dst] = lo;
        B[dst + 1] = hi;
      }
    }

    // ---- chi ----
    for (let y = 0; y < 5; y++) {
      for (let x = 0; x < 5; x++) {
        const cur = 2 * (x + 5 * y);
        const n1 = 2 * (((x + 1) % 5) + 5 * y);
        const n2 = 2 * (((x + 2) % 5) + 5 * y);
        s[cur] = B[cur] ^ (~B[n1] & B[n2]);
        s[cur + 1] = B[cur + 1] ^ (~B[n1 + 1] & B[n2 + 1]);
      }
    }

    // ---- iota ----
    s[0] ^= RC_LO[round];
    s[1] ^= RC_HI[round];
  }
}

/**
 * 计算 Keccak-256 摘要。
 * @param {Uint8Array|Buffer} data 输入字节
 * @returns {Uint8Array} 32 字节摘要
 */
function keccak256(data) {
  const len = data.length;
  const padLen = RATE_BYTES - (len % RATE_BYTES);
  const total = len + padLen;

  const padded = new Uint8Array(total);
  padded.set(data, 0);
  padded[len] ^= 0x01;
  padded[total - 1] ^= 0x80;

  const state = new Uint32Array(50);

  for (let off = 0; off < total; off += RATE_BYTES) {
    for (let w = 0; w < RATE_WORDS; w++) {
      const b = off + w * 4;
      state[w] ^= (padded[b] | (padded[b + 1] << 8) | (padded[b + 2] << 16) | (padded[b + 3] << 24)) >>> 0;
    }
    keccakF1600(state);
  }

  const out = new Uint8Array(32);
  for (let w = 0; w < 8; w++) {
    const v = state[w];
    out[w * 4] = v & 0xff;
    out[w * 4 + 1] = (v >>> 8) & 0xff;
    out[w * 4 + 2] = (v >>> 16) & 0xff;
    out[w * 4 + 3] = (v >>> 24) & 0xff;
  }
  return out;
}

module.exports = { keccak256, keccakF1600 };
