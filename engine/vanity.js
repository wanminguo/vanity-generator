/**
 * 揽号引擎主控（CLI，多链 + 批量）。
 *
 * 用法：
 *   node engine/vanity.js --prefix 8888
 *   node engine/vanity.js --chain btc --suffix 888 --threads 12
 *   node engine/vanity.js --count 10 --suffix 888 --threads 8
 *
 * 输出协议：stdout 每行一个 JSON 对象（供 UI 逐行读取）
 *   {"t":"ready","threads":12,"chain":"eth","chainTag":"ETH","unit":"hex","target":65536,"count":1}
 *   {"t":"progress","attempts":...,"rate":...,"elapsed":...,"eta":...,"target":...,"collected":..,"count":..}
 *   {"t":"found","index":3,"count":10,"address":"...","matchKey":"...","privHex":"...","attempts":..,"elapsed":..,"rate":..}
 *   {"t":"done","collected":10,"attempts":..,"elapsed":..}
 *   {"t":"stopped"} / {"t":"error","message":"..."}
 *
 * 本文件不引入任何网络模块；不读取、不写入任何用户文件。
 */

const os = require('node:os');
const path = require('node:path');
const { Worker } = require('node:worker_threads');
const { CHAIN_IDS, getChain } = require('./chains.js');

function parseArgs(argv) {
  const out = {
    prefix: '',
    suffix: '',
    rules: null,
    threads: Math.max(1, os.cpus().length),
    intervalMs: 300,
    chain: 'eth',
    count: 1,
  };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    const next = () => argv[++i];
    if (a === '--prefix') out.prefix = String(next() || '');
    else if (a === '--suffix') out.suffix = String(next() || '');
    else if (a === '--rules') out.rules = String(next() || '');
    else if (a === '--threads') out.threads = Math.max(1, parseInt(next(), 10) || 1);
    else if (a === '--interval') out.intervalMs = Math.max(100, parseInt(next(), 10) || 300);
    else if (a === '--chain') out.chain = String(next() || 'eth').toLowerCase();
    else if (a === '--count') out.count = Math.max(1, parseInt(next(), 10) || 1);
  }
  return out;
}

const emit = (obj) => {
  process.stdout.write(JSON.stringify(obj) + '\n');
};

function fail(message) {
  emit({ t: 'error', message });
  process.exit(2);
}

function main() {
  const args = parseArgs(process.argv);

  if (!CHAIN_IDS.includes(args.chain)) {
    fail(`未知链 "${args.chain}"，可选：${CHAIN_IDS.join(' / ')}`);
  }
  const chain = getChain(args.chain);
  const isEvm = chain.kind === 'evm';

  // EVM 地址 40 位 hex；Base58 地址约 26～35 位，按 34 保守限制
  const maxLen = isEvm ? 40 : 34;
  const normalize = (s) =>
    isEvm ? String(s).trim().replace(/^0x/i, '').toLowerCase() : String(s).trim();

  // ---- 规则集合：--rules 传 JSON 数组（多条并行），否则用单条 --prefix/--suffix
  let rawRules = null;
  if (args.rules) {
    try {
      rawRules = JSON.parse(args.rules);
    } catch {
      fail('--rules 需要合法 JSON，例如 \'[{"prefix":"888"},{"suffix":"777"}]\'');
    }
    if (!Array.isArray(rawRules) || rawRules.length === 0) {
      fail('--rules 需要非空数组');
    }
  }

  const rules = (rawRules || [{ prefix: args.prefix, suffix: args.suffix }]).map((r) => ({
    prefix: normalize(r && r.prefix ? r.prefix : ''),
    suffix: normalize(r && r.suffix ? r.suffix : ''),
  }));

  if (rules.length > 64) {
    fail(`规则最多 64 条，当前 ${rules.length} 条`);
  }

  rules.forEach((r, i) => {
    const label = `第 ${i + 1} 条规则`;
    for (const ch of r.prefix + r.suffix) {
      if (!chain.alphabet.includes(ch)) {
        fail(`${label}含非法字符 "${ch}"。${chain.tag} 地址可用字符：${isEvm ? '0-9 a-f' : chain.alphabet}`);
      }
    }
    if (r.prefix.length + r.suffix.length > maxLen) {
      fail(`${label}前缀 + 后缀共 ${r.prefix.length + r.suffix.length} 位，超过 ${chain.tag} 地址长度上限 ${maxLen} 位`);
    }
  });

  const prefix = rules[0].prefix;
  const suffix = rules[0].suffix;

  // EVM 固定 n 位平均 16^n 次；Base58 字符集 58，平均 58^n 次（BTC 首位固定为 1，此处仍按保守值给出）
  const base = isEvm ? 16 : 58;
  const ruleTargets = rules.map((r) => {
    const fixed = r.prefix.length + r.suffix.length;
    return fixed === 0 ? 1 : Math.pow(base, fixed);
  });

  // 多规则并行时命中概率相加：等价期望次数 = 1 / Σ(1/单条期望)
  const totalInv = ruleTargets.reduce((sum, t) => sum + 1 / t, 0);
  const target = totalInv > 0 ? Math.max(1, 1 / totalInv) : 1;
  const fixedChars = Math.max(...rules.map((r) => r.prefix.length + r.suffix.length));

  const threads = Math.min(Math.max(1, args.threads), 256);
  const wantCount = Math.min(Math.max(1, args.count), 100000);
  const workerPath = path.join(__dirname, 'worker.js');

  const counterBuf = new SharedArrayBuffer(8);
  const counter = new BigInt64Array(counterBuf);

  const startedAt = Date.now();
  const workers = [];
  let timer = null;
  let collected = 0;
  let finished = false;

  const shutdown = (code) => {
    if (timer) clearInterval(timer);
    timer = null;
    for (const w of workers) {
      try {
        w.terminate();
      } catch {
        /* 已结束 */
      }
    }
    setTimeout(() => process.exit(code), 30);
  };

  const nowStats = () => {
    const elapsed = (Date.now() - startedAt) / 1000;
    const total = Number(Atomics.load(counter, 0));
    const rate = elapsed > 0 ? Math.round(total / elapsed) : 0;
    return { elapsed, total, rate };
  };

  function onFound(hit) {
    if (finished) return;

    collected += 1;
    const { elapsed, total, rate } = nowStats();

    emit({
      t: 'found',
      index: collected,
      count: wantCount,
      address: hit.address,
      // EVM 额外给出不带校验和的小写形式；非 EVM 链无此概念，给 null
      addressLower: isEvm ? hit.address.toLowerCase() : null,
      matchKey: isEvm ? hit.address.replace(/^0x/i, '').toLowerCase() : null,
      privHex: hit.privHex,
      ruleIndex: hit.ruleIndex || 0,
      attempts: total,
      elapsed: Number(elapsed.toFixed(2)),
      rate,
    });

    if (collected >= wantCount) {
      finished = true;
      emit({
        t: 'done',
        collected,
        attempts: total,
        elapsed: Number(elapsed.toFixed(2)),
      });
      shutdown(0);
    }
  }

  emit({
    t: 'ready',
    threads,
    chain: args.chain,
    chainTag: chain.tag,
    unit: chain.unit,
    target,
    fixedChars,
    prefix,
    suffix,
    rules,
    ruleCount: rules.length,
    count: wantCount,
  });

  for (let i = 0; i < threads; i++) {
    const worker = new Worker(workerPath, {
      workerData: { prefix, suffix, rules, chain: args.chain, counter: counterBuf },
    });
    workers.push(worker);

    worker.on('message', (msg) => {
      if (msg && msg.t === 'found') onFound(msg);
    });
    worker.on('error', (err) => {
      if (!finished) fail(`工作线程出错：${err && err.message ? err.message : String(err)}`);
    });
  }

  timer = setInterval(() => {
    if (finished) return;
    const { elapsed, total, rate } = nowStats();
    const remainHits = Math.max(1, wantCount - collected);
    const eta = rate > 0 ? Math.max(0, Math.round((target * remainHits - total) / rate)) : null;
    emit({
      t: 'progress',
      attempts: total,
      rate,
      elapsed: Number(elapsed.toFixed(1)),
      eta,
      target,
      collected,
      count: wantCount,
    });
  }, args.intervalMs);

  process.on('SIGINT', () => {
    emit({ t: 'stopped', collected });
    shutdown(0);
  });
}

process.on('uncaughtException', (err) => {
  emit({ t: 'error', message: err && err.message ? err.message : String(err) });
  process.exit(1);
});

main();
