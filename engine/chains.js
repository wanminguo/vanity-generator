/**
 * 多链地址派生。
 *
 * EVM 系（eth/bsc/polygon/arbitrum/base）：地址格式完全相同，同一私钥通用，
 *   区别只在链上网络，界面仅作标识。
 * 非 EVM：
 *   btc / doge —— P2PKH：ripemd160(sha256(压缩公钥)) + 版本字节 → Base58Check
 *   trx        —— 0x41 + keccak256(公钥)[12:] → Base58Check
 *
 * 依赖：node:crypto（OpenSSL 提供 secp256k1、sha256、ripemd160），无第三方库。
 */

const crypto = require('node:crypto');
const { keccak256 } = require('./keccak.js');
const { encodeCheck, BASE58_ALPHABET } = require('./base58.js');

const HEX = '0123456789abcdef';

const CHAINS = {
  eth: { tag: 'ETH', name: 'Ethereum', kind: 'evm', alphabet: HEX, unit: 'hex' },
  bsc: { tag: 'BSC', name: 'BNB Chain', kind: 'evm', alphabet: HEX, unit: 'hex' },
  polygon: { tag: 'POLYGON', name: 'Polygon', kind: 'evm', alphabet: HEX, unit: 'hex' },
  arbitrum: { tag: 'ARB', name: 'Arbitrum One', kind: 'evm', alphabet: HEX, unit: 'hex' },
  base: { tag: 'BASE', name: 'Base', kind: 'evm', alphabet: HEX, unit: 'hex' },
  btc: { tag: 'BTC', name: 'Bitcoin', kind: 'p2pkh', version: 0x00, alphabet: BASE58_ALPHABET, unit: 'base58' },
  doge: { tag: 'DOGE', name: 'Dogecoin', kind: 'p2pkh', version: 0x1e, alphabet: BASE58_ALPHABET, unit: 'base58' },
  trx: { tag: 'TRX', name: 'TRON', kind: 'tron', version: 0x41, alphabet: BASE58_ALPHABET, unit: 'base58' },
};

const CHAIN_IDS = Object.keys(CHAINS);

function getChain(id) {
  const chain = CHAINS[String(id || 'eth').toLowerCase()];
  if (!chain) throw new Error(`未知链: ${id}`);
  return chain;
}

/** EIP-55 校验和格式（仅 EVM 用） */
function toChecksumAddress(addrHexLower) {
  const lower = addrHexLower.replace(/^0x/i, '').toLowerCase();
  const hash = Buffer.from(keccak256(Buffer.from(lower, 'utf8'))).toString('hex');
  let out = '0x';
  for (let i = 0; i < 40; i++) {
    const ch = lower[i];
    if (ch >= '0' && ch <= '9') out += ch;
    else out += parseInt(hash[i], 16) >= 8 ? ch.toUpperCase() : ch;
  }
  return out;
}

function toHex(buf, len) {
  let out = '';
  for (let i = 0; i < len; i++) {
    const b = buf[i];
    out += (b < 16 ? '0' : '') + b.toString(16);
  }
  return out;
}

/** 压缩公钥：0x02/0x03 || X(32) */
function compressPub(uncompressed65) {
  const x = uncompressed65.subarray(1, 33);
  const yLast = uncompressed65[64];
  const prefix = yLast % 2 === 0 ? 0x02 : 0x03;
  return Buffer.concat([Buffer.from([prefix]), Buffer.from(x)]);
}

class ChainDeriver {
  constructor(chainId) {
    this.chain = getChain(chainId);
    this.ecdh = crypto.createECDH('secp256k1');
    this._pub = null;
  }

  _publicKey(priv) {
    this.ecdh.setPrivateKey(priv);
    this._pub = this.ecdh.getPublicKey(); // 65 字节未压缩
    return this._pub;
  }

  /**
   * @returns {{ address: string, matchKey: string }}
   *   address  —— 完整展示地址
   *   matchKey —— 用于前缀/后缀匹配的字符串（EVM 为不含 0x 的小写 hex；其他为地址原文）
   */
  derive(priv) {
    const pub = this._publicKey(priv);

    if (this.chain.kind === 'evm') {
      const h = keccak256(pub.subarray(1));
      const lower = toHex(h.subarray(12, 32), 20);
      return { address: toChecksumAddress(lower), matchKey: lower };
    }

    if (this.chain.kind === 'p2pkh') {
      const compressed = compressPub(pub);
      const h160 = crypto.createHash('ripemd160')
        .update(crypto.createHash('sha256').update(compressed).digest())
        .digest();
      const payload = Buffer.concat([Buffer.from([this.chain.version]), h160]);
      return { address: encodeCheck(payload), matchKey: null };
    }

    if (this.chain.kind === 'tron') {
      const h = keccak256(pub.subarray(1));
      const payload = Buffer.concat([Buffer.from([this.chain.version]), Buffer.from(h.subarray(12, 32))]);
      return { address: encodeCheck(payload), matchKey: null };
    }

    throw new Error(`未实现的链类型: ${this.chain.kind}`);
  }

  /** 匹配用字符串，EVM 已由 derive 返回，其他链直接用地址原文（区分大小写） */
  keyOf(derived) {
    return derived.matchKey === null ? derived.address : derived.matchKey;
  }
}

module.exports = { ChainDeriver, CHAINS, CHAIN_IDS, getChain, toChecksumAddress };
