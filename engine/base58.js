/**
 * Base58 / Base58Check 编码（比特币、TRON、Dogecoin 地址用）。
 * 只用 node:crypto 的 sha256，不引入第三方库。
 */

const crypto = require('node:crypto');

const ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
const ALPHABET_MAP = (() => {
  const m = new Map();
  for (let i = 0; i < ALPHABET.length; i++) m.set(ALPHABET[i], BigInt(i));
  return m;
})();

/** 纯 Base58 编码（不含校验） */
function encodeRaw(buf) {
  let zeros = 0;
  while (zeros < buf.length && buf[zeros] === 0) zeros++;

  let n = 0n;
  for (let i = 0; i < buf.length; i++) n = n * 256n + BigInt(buf[i]);

  let out = '';
  while (n > 0n) {
    const rem = n % 58n;
    out = ALPHABET[Number(rem)] + out;
    n /= 58n;
  }
  // 前导零每个对应一个 '1'
  for (let i = 0; i < zeros; i++) out = '1' + out;
  return out === '' ? '1' : out;
}

/** 纯 Base58 解码 */
function decodeRaw(str) {
  let zeros = 0;
  while (zeros < str.length && str[zeros] === '1') zeros++;

  let n = 0n;
  for (const ch of str) {
    const v = ALPHABET_MAP.get(ch);
    if (v === undefined) throw new Error(`非法 Base58 字符: ${ch}`);
    n = n * 58n + v;
  }

  const bytes = [];
  while (n > 0n) {
    bytes.unshift(Number(n % 256n));
    n /= 256n;
  }
  for (let i = 0; i < zeros; i++) bytes.unshift(0);
  return Buffer.from(bytes);
}

function sha256(buf) {
  return crypto.createHash('sha256').update(buf).digest();
}

/** 双 SHA256 校验和，取前 4 字节 */
function checksum(buf) {
  return sha256(sha256(buf)).subarray(0, 4);
}

/** Base58Check 编码：payload + 4 字节校验 */
function encodeCheck(payload) {
  return encodeRaw(Buffer.concat([payload, checksum(payload)]));
}

/** Base58Check 解码：校验失败抛错 */
function decodeCheck(str) {
  const raw = decodeRaw(str);
  if (raw.length < 5) throw new Error('地址过短');
  const payload = raw.subarray(0, raw.length - 4);
  const want = raw.subarray(raw.length - 4);
  const got = checksum(payload);
  if (!want.equals(got)) throw new Error('校验和不匹配');
  return payload;
}

const BASE58_ALPHABET = ALPHABET;

module.exports = { encodeRaw, decodeRaw, encodeCheck, decodeCheck, BASE58_ALPHABET };
