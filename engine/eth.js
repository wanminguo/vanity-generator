/**
 * 以太坊地址派生 —— 私钥 → 公钥 → Keccak-256 → 地址（含 EIP-55 校验和）
 *
 * 依赖：node:crypto 内置 secp256k1（OpenSSL 实现），本项目不引入任何网络库。
 * 密码学不自行实现：只借用系统内置的曲线运算；Keccak-256 因 node 未提供而自带实现（见 keccak.js）。
 */

const crypto = require('node:crypto');
const { keccak256 } = require('./keccak.js');

/**
 * 可复用的地址生成器：复用同一个 ECDH 实例以避免对象创建开销。
 * 每次 derive() 会覆盖内部公钥缓冲，因此返回的地址是 20 字节新数组（安全）。
 */
class EthKeyDeriver {
  constructor() {
    this.ecdh = crypto.createECDH('secp256k1');
    this._pub = null;
    this._hash = null;
  }

  /**
   * @param {Buffer|Uint8Array} priv 32 字节私钥
   * @returns {Uint8Array} 20 字节地址
   */
  derive(priv) {
    this.ecdh.setPrivateKey(priv);
    // 65 字节未压缩公钥：0x04 || X(32) || Y(32)
    this._pub = this.ecdh.getPublicKey();
    const h = keccak256(this._pub.subarray(1));
    return h.subarray(12, 32);
  }

  /**
   * 只取地址的十六进制小写字符串（40 字符，不含 0x）。
   * @param {Buffer|Uint8Array} priv
   * @returns {string}
   */
  deriveHex(priv) {
    const addr = this.derive(priv);
    let out = '';
    for (let i = 0; i < 20; i++) {
      const b = addr[i];
      out += (b < 16 ? '0' : '') + b.toString(16);
    }
    return out;
  }
}

/** 私钥合法性检查：0 < k < n */
const SECP256K1_N = BigInt('0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141');

function isValidPrivateKey(priv) {
  const hex = Buffer.from(priv).toString('hex');
  const k = BigInt('0x' + hex);
  return k > 0n && k < SECP256K1_N;
}

/** EIP-55 校验和地址：0x 前缀 + 依 Keccak256(lowercase) 决定字母大小写 */
function toChecksumAddress(addrHexLower) {
  const lower = addrHexLower.replace(/^0x/i, '').toLowerCase();
  const hash = Buffer.from(keccak256(Buffer.from(lower, 'utf8'))).toString('hex');
  let out = '0x';
  for (let i = 0; i < 40; i++) {
    const ch = lower[i];
    if (ch >= '0' && ch <= '9') {
      out += ch;
    } else {
      out += parseInt(hash[i], 16) >= 8 ? ch.toUpperCase() : ch;
    }
  }
  return out;
}

module.exports = { EthKeyDeriver, isValidPrivateKey, toChecksumAddress, SECP256K1_N };
