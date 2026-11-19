/**
 * 端到端测试：真实启动多线程揽号引擎，验证「找到的地址确实满足规则」。
 * 运行：node tests/e2e.js
 */

const { spawn } = require('node:child_process');
const path = require('node:path');
const { EthKeyDeriver, toChecksumAddress } = require('../engine/eth.js');

const ENGINE = path.join(__dirname, '..', 'engine', 'vanity.js');

function runCase({ prefix = '', suffix = '', threads = 6 }) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [ENGINE, '--prefix', prefix, '--suffix', suffix,
      '--threads', String(threads), '--interval', '400'], { cwd: path.join(__dirname, '..') });

    const events = [];
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`超时未命中：prefix=${prefix} suffix=${suffix}`));
    }, 60000);

    child.stdout.on('data', (chunk) => {
      for (const line of chunk.toString('utf8').split('\n')) {
        if (!line.trim()) continue;
        let evt;
        try {
          evt = JSON.parse(line);
        } catch {
          continue;
        }
        events.push(evt);
        if (evt.t === 'found' || evt.t === 'error') {
          clearTimeout(timer);
          child.kill();
          if (evt.t === 'error') reject(new Error(evt.message));
          else resolve(evt);
        }
      }
    });
    child.stderr.on('data', (d) => {
      clearTimeout(timer);
      child.kill();
      reject(new Error('引擎 stderr: ' + d.toString()));
    });
  });
}

(async () => {
  let failures = 0;
  const check = (name, cond, detail = '') => {
    if (cond) {
      console.log(`  PASS  ${name}`);
    } else {
      failures++;
      console.log(`  FAIL  ${name} ${detail}`);
    }
  };

  console.log('[1] 前缀 3 位（aba）');
  const a = await runCase({ prefix: 'aba', threads: 6 });
  const addrLower = a.addressLower.slice(2);
  check('地址满足前缀', addrLower.startsWith('aba'), a.address);
  check('地址长度为 40 位', addrLower.length === 40, addrLower.length);
  check('私钥 32 字节', a.privHex.length === 64, a.privHex.length);
  check('EIP-55 格式', /^0x[0-9a-fA-F]{40}$/.test(a.address), a.address);

  // 私钥必须能反推出同一个地址（这是最关键的校验）
  const deriver = new EthKeyDeriver();
  const derived = deriver.deriveHex(Buffer.from(a.privHex, 'hex'));
  check('私钥可复现地址', derived === addrLower, `${derived} != ${addrLower}`);
  check('checksum 正确', toChecksumAddress(derived) === a.address, toChecksumAddress(derived));

  console.log('[2] 后缀 3 位（beef）');
  const b = await runCase({ suffix: 'beef', threads: 6 });
  const addrLowerB = b.addressLower.slice(2);
  check('地址满足后缀', addrLowerB.endsWith('beef'), b.address);
  const deriverB = new EthKeyDeriver();
  check('私钥可复现地址', deriverB.deriveHex(Buffer.from(b.privHex, 'hex')) === addrLowerB);

  console.log('[3] 前后缀同时指定');
  const c = await runCase({ prefix: 'c', suffix: 'ab', threads: 6 });
  check('前缀 c', c.addressLower.slice(2).startsWith('c'), c.address);
  check('后缀 ab', c.addressLower.slice(2).endsWith('ab'), c.address);

  console.log('[4] 空规则（随机地址）');
  const d = await runCase({ threads: 3 });
  check('返回合法地址', /^0x[0-9a-fA-F]{40}$/.test(d.address), d.address);
  check('返回合法私钥', /^[0-9a-f]{64}$/.test(d.privHex), d.privHex.slice(0, 8));

  console.log(`\n结果：${failures === 0 ? '全部通过' : failures + ' 项失败'}`);
  process.exit(failures === 0 ? 0 : 1);
})().catch((err) => {
  console.error('测试异常：', err.message);
  process.exit(1);
});
