/**
 * 揽号搜索工作线程（多链版）。
 *
 * 每个线程独立循环：随机私钥 → 公钥 → 按链编码地址 → 匹配规则。
 * 命中后立即上报，然后继续搜索（批量模式下主线程会累计到 N 个后终止本线程）。
 *
 * 私钥只存在于本进程内存中，随进程结束销毁；不落盘、不上传。
 * 本文件不引入任何网络模块。
 */

const { parentPort, workerData } = require('node:worker_threads');
const crypto = require('node:crypto');
const { ChainDeriver } = require('./chains.js');

const prefix = workerData.prefix || '';
const suffix = workerData.suffix || '';
const batchSize = workerData.batchSize || 512;
const chainId = workerData.chain || 'eth';
const counter = new BigInt64Array(workerData.counter);

// 多规则并行：每条规则一个前缀/后缀组合，命中任意一条即算命中
const rules = (workerData.rules && workerData.rules.length)
  ? workerData.rules
  : [{ prefix, suffix }];

const deriver = new ChainDeriver(chainId);

/** 返回命中的规则下标；都不命中返回 -1 */
function hitIndex(key) {
  for (let i = 0; i < rules.length; i++) {
    const r = rules[i];
    if (r.prefix && !key.startsWith(r.prefix)) continue;
    if (r.suffix && !key.endsWith(r.suffix)) continue;
    return i;
  }
  return -1;
}

/**
 * 搜索一个批次。命中返回 { address, privHex }，否则返回 null。
 * 私钥一次性批量生成，摊薄 randomBytes 的调用开销。
 */
function searchBatch() {
  const buf = crypto.randomBytes(32 * batchSize);

  for (let i = 0; i < batchSize; i++) {
    const off = i * 32;
    const priv = buf.subarray(off, off + 32);

    let derived;
    try {
      derived = deriver.derive(priv);
    } catch {
      // 仅当私钥为 0 或 >= 曲线阶时抛错（概率约 2^-128）
      continue;
    }

    const key = deriver.keyOf(derived);
    const hit = hitIndex(key);
    if (hit < 0) continue;

    // 只累加到实际试到的位置，避免多报整批
    Atomics.add(counter, 0, BigInt(i + 1));
    return { address: derived.address, privHex: Buffer.from(priv).toString('hex'), ruleIndex: hit };
  }

  Atomics.add(counter, 0, BigInt(batchSize));
  return null;
}

// 持续搜索，直到主线程 terminate
for (;;) {
  const hit = searchBatch();
  if (hit) {
    parentPort.postMessage({
      t: 'found',
      address: hit.address,
      privHex: hit.privHex,
      ruleIndex: hit.ruleIndex,
      attempts: Number(Atomics.load(counter, 0)),
    });
  }
}
