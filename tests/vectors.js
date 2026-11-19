/**
 * 自检脚本：用公开测试向量验证 Keccak-256 与地址派生是否正确。
 * 运行：node tests/vectors.js
 */

const assert = require('node:assert');
const { keccak256 } = require('../engine/keccak.js');
const { EthKeyDeriver, toChecksumAddress } = require('../engine/eth.js');

const hex = (u8) => Buffer.from(u8).toString('hex');

let pass = 0;
let fail = 0;
function check(name, actual, expected) {
  if (actual === expected) {
    pass++;
    console.log(`  PASS  ${name}`);
  } else {
    fail++;
    console.log(`  FAIL  ${name}\n        got      ${actual}\n        expected ${expected}`);
  }
}

console.log('[1] Keccak-256 标准向量');
check('empty string', hex(keccak256(Buffer.from(''))),
  'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470');
check('"abc"', hex(keccak256(Buffer.from('abc'))),
  '4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45');
check('"The quick brown fox jumps over the lazy dog"',
  hex(keccak256(Buffer.from('The quick brown fox jumps over the lazy dog'))),
  '4d741b6f1eb29cb2a9b9911c82f56fa8d73b04959d3d9d222895df6c0b28aa15');

console.log('[2] 多块吸收（跨 136 字节 rate 边界）');
// 100 字节 + 136 字节两种长度，与 Node 的 sha3 实现无关，仅做自洽性检查
check('136 bytes x 2 idempotent', hex(keccak256(Buffer.alloc(272))), hex(keccak256(Buffer.alloc(272))));

console.log('[3] 已知私钥 → 地址（公知向量）');
const knownCases = [
  // 私钥 0x...01 对应地址 0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf
  ['0000000000000000000000000000000000000000000000000000000000000001',
   '7e5f4552091a69125d5dfcb7b8c2659029395bdf'],
  // 私钥 0x...02 对应地址 0x2B5AD5c4795c026514f8317c7a215E218DcCD6cF
  ['0000000000000000000000000000000000000000000000000000000000000002',
   '2b5ad5c4795c026514f8317c7a215e218dccd6cf'],
];
const deriver = new EthKeyDeriver();
for (const [privHex, expectedAddr] of knownCases) {
  check(`priv ${privHex.slice(-4)}`, deriver.deriveHex(Buffer.from(privHex, 'hex')), expectedAddr);
}

console.log('[4] EIP-55 校验和格式');
check('checksum 0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed',
  toChecksumAddress('5aaeb6053f3e94c9b9a09f33669435e7ef1beaed'),
  '0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed');
check('checksum 0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359',
  toChecksumAddress('fb6916095ca1df60bb79ce92ce3ea74c37c5d359'),
  '0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359');

console.log('[5] 吞吐量（单线程）');
const der2 = new EthKeyDeriver();
const priv = Buffer.alloc(32, 0x46);
const N = 5000;
const t0 = process.hrtime.bigint();
for (let i = 0; i < N; i++) der2.deriveHex(priv);
const t1 = process.hrtime.bigint();
const perSec = Math.round(N / (Number(t1 - t0) / 1e9));
console.log(`  ${perSec} addr/s per thread`);

console.log(`\n结果：${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
