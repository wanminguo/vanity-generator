/**
 * 多链派生测试：Base58Check 回环、BTC/DOGE/TRON 地址、EVM 各链一致性。
 * 运行：node tests/chains.js
 */

const assert = require('node:assert');
const crypto = require('node:crypto');

const { ChainDeriver, CHAIN_IDS, getChain, toChecksumAddress } = require('../engine/chains.js');
const { encodeCheck, decodeCheck, encodeRaw, decodeRaw } = require('../engine/base58.js');
const { keccak256 } = require('../engine/keccak.js');

let passed = 0;
let failed = 0;

function check(name, fn) {
  try {
    fn();
    passed++;
    console.log(`  PASS  ${name}`);
  } catch (err) {
    failed++;
    console.log(`  FAIL  ${name}`);
    console.log(`        ${err.message}`);
  }
}

function toHex(buf, len) {
  let out = '';
  for (let i = 0; i < len; i++) out += (buf[i] < 16 ? '0' : '') + buf[i].toString(16);
  return out;
}

const PRIV1 = Buffer.from('00'.repeat(31) + '01', 'hex');

console.log('[1] Base58/Base58Check 编解码');
check('随机字节 encode→decode 回环 50 次', () => {
  for (let i = 0; i < 50; i++) {
    const buf = crypto.randomBytes(1 + (i % 40));
    const enc = encodeRaw(buf);
    const dec = decodeRaw(enc);
    assert.equal(toHex(dec, dec.length), toHex(buf, buf.length));
  }
});

check('前导零字节保持为 "1"', () => {
  const buf = Buffer.from([0, 0, 1, 2, 3]);
  const enc = encodeRaw(buf);
  assert.ok(enc.startsWith('11'), `前导零应编码为 11，实际 ${enc}`);
  const dec = decodeRaw(enc);
  assert.equal(toHex(dec, dec.length), '0000010203');
});

check('Base58Check 校验和检测（篡改后必须抛错）', () => {
  const payload = Buffer.from([0x00, ...crypto.randomBytes(20)]);
  const addr = encodeCheck(payload);
  const decoded = decodeCheck(addr);
  assert.equal(toHex(decoded, decoded.length), toHex(payload, payload.length));

  const bad = addr.slice(0, -1) + (addr.endsWith('1') ? '2' : '1');
  let threw = false;
  try {
    decodeCheck(bad);
  } catch {
    threw = true;
  }
  assert.ok(threw, '篡改后的地址应无法通过校验');
});

check('非法字符必须抛错', () => {
  let threw = false;
  try {
    decodeRaw('0OIl');
  } catch {
    threw = true;
  }
  assert.ok(threw);
});

console.log('[2] BTC / DOGE / TRON 地址');

check('BTC 私钥 0x…01 → 1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH（公知向量）', () => {
  const d = new ChainDeriver('btc');
  const r = d.derive(PRIV1);
  assert.equal(r.address, '1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH');
});

check('BTC 地址版本字节为 0x00', () => {
  const d = new ChainDeriver('btc');
  const payload = decodeCheck(d.derive(PRIV1).address);
  assert.equal(payload[0], 0x00);
});

check('DOGE 地址版本字节为 0x1e', () => {
  const d = new ChainDeriver('doge');
  const payload = decodeCheck(d.derive(PRIV1).address);
  assert.equal(payload[0], 0x1e);
});

check('TRON 地址 = Base58Check(0x41 + keccak(公钥)[12:])', () => {
  const d = new ChainDeriver('trx');
  const payload = decodeCheck(d.derive(PRIV1).address);
  assert.equal(payload[0], 0x41);

  // 与 ETH 地址的后 20 字节必须一致（同一条曲线、同一份公钥）
  const pub = crypto.createECDH('secp256k1');
  pub.setPrivateKey(PRIV1);
  const uncompressed = pub.getPublicKey();
  const h = keccak256(uncompressed.subarray(1));
  assert.equal(toHex(payload.subarray(1), 20), toHex(h.subarray(12, 32), 20));
});

check('TRON 地址以 T 开头且长度 34', () => {
  const addr = new ChainDeriver('trx').derive(PRIV1).address;
  assert.ok(addr.startsWith('T'), `TRON 地址应以 T 开头，实际 ${addr}`);
  assert.equal(addr.length, 34);
});

console.log('[3] EVM 各链一致性');

check('同一私钥在 5 条 EVM 链上地址完全相同', () => {
  const evmIds = CHAIN_IDS.filter((id) => getChain(id).kind === 'evm');
  assert.equal(evmIds.length, 5);
  const addrs = new Set();
  for (const id of evmIds) addrs.add(new ChainDeriver(id).derive(PRIV1).address);
  assert.equal(addrs.size, 1, `应只有 1 个地址，实际 ${addrs.size}`);
});

check('EVM 地址 = 已知向量 0x7E5F4552…5Bdf', () => {
  assert.equal(
    new ChainDeriver('eth').derive(PRIV1).address.toLowerCase(),
    '0x7e5f4552091a69125d5dfcb7b8c2659029395bdf',
  );
});

check('matchKey 规则：EVM 为小写 hex，非 EVM 为地址原文', () => {
  const evm = new ChainDeriver('eth');
  const r1 = evm.derive(PRIV1);
  assert.equal(r1.matchKey, r1.address.replace('0x', '').toLowerCase());

  const btc = new ChainDeriver('btc');
  const r2 = btc.derive(PRIV1);
  assert.equal(btc.keyOf(r2), r2.address);
});

console.log('[4] 各链字母表');
check('EVM 链 alphabet 为 hex，非 EVM 为 base58', () => {
  assert.equal(getChain('eth').alphabet, '0123456789abcdef');
  const b58 = getChain('btc').alphabet;
  assert.equal(b58.length, 58);
  for (const bad of ['0', 'O', 'I', 'l']) assert.ok(!b58.includes(bad), `base58 不应含 ${bad}`);
});

console.log(`\n结果：${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
