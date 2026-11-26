// Isolated fixtures only; never opens the user's actual WebView data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {ClassicLevel} = require('classic-level');
const {decodeString, encodeString, editState, repairDatabase} = require('./verge_latency.cjs');

(async () => {
  const tempRoot = fs.realpathSync(os.tmpdir());
  const workspace = fs.mkdtempSync(path.join(tempRoot, 'qizhi-latency-test-'));
  const key = Buffer.concat([Buffer.from('_http://tauri.localhost\0'), encodeString('proxy-head-state', 1)]);
  const fixture = {
    active: {Qizhi: {open: true, sortType: 2, testUrl: '', filterText: 'keep'},
             Outside: {testUrl: 'https://example.test/', showType: false}},
    otherProfile: {Qizhi: {testUrl: 'https://other.test/'}}
  };
  const untouched = Buffer.from([0, 1, 2, 253, 254, 255]);
  try {
    for (const marker of [0, 1]) {
      const database = path.join(workspace, 'db-' + marker);
      let db = new ClassicLevel(database, {keyEncoding: 'buffer', valueEncoding: 'buffer'});
      await db.put(key, encodeString(JSON.stringify(fixture), marker));
      await db.put(Buffer.from('unrelated'), untouched);
      await assert.rejects(repairDatabase({mode:'patch',database,profile:'active',group:'Qizhi',backup:path.join(workspace,'locked-backup')}));
      assert(!fs.existsSync(path.join(workspace, 'locked-backup')));
      await db.close();
      const options = {mode: 'patch', database, profile: 'active', group: 'Qizhi', backup: path.join(workspace, 'backup-' + marker)};
      const inspection = await repairDatabase({...options, mode: 'inspect'});
      assert.equal(inspection.testUrl, '');
      assert(!fs.existsSync(options.backup));
      const repaired = await repairDatabase(options);
      assert.equal(repaired.status, 'patched');
      assert.equal((await repairDatabase(options)).status, 'already_configured');
      db = new ClassicLevel(database, {keyEncoding: 'buffer', valueEncoding: 'buffer'});
      const final = JSON.parse(decodeString(await db.get(key)));
      assert.equal(final.active.Qizhi.testUrl, 'https://qz.sii.edu.cn/');
      final.active.Qizhi.testUrl = '';
      assert.deepEqual(final, fixture);
      assert((await db.get(Buffer.from('unrelated'))).equals(untouched));
      await db.close();
      const backup = new ClassicLevel(path.join(options.backup, 'leveldb'), {keyEncoding: 'buffer', valueEncoding: 'buffer', createIfMissing: false});
      assert.deepEqual(JSON.parse(decodeString(await backup.get(key))), fixture);
      await backup.close();
      await assert.rejects(repairDatabase({...options,profile:'missing'}));
    }
    assert.throws(() => editState(fixture, 'missing', 'Qizhi', 'https://qz.sii.edu.cn/'));
    assert.throws(() => editState(fixture, 'active', '__proto__', 'https://qz.sii.edu.cn/'));
    assert.equal(editState(fixture,'active','NewQizhi','https://qz.sii.edu.cn/').active.NewQizhi.testUrl,'https://qz.sii.edu.cn/');
    assert.equal(decodeString(encodeString('启智', 1)), '启智');
    console.log('Latency repair: UTF-16/Latin-1, isolated field update, lock refusal, backup recovery and idempotency passed');
  } finally {
    const resolved = fs.realpathSync(workspace);
    assert.equal(path.dirname(resolved), tempRoot);
    assert(path.basename(resolved).startsWith('qizhi-latency-test-'));
    fs.rmSync(resolved, {recursive: true});
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
