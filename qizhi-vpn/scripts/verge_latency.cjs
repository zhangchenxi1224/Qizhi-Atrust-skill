// Optional, offline WebView2 Local Storage repair. Never manages application processes.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const DEFAULT_URL = 'https://qz.sii.edu.cn/';
const ORIGIN = '_http://tauri.localhost';
const FIELD = 'proxy-head-state';
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const owns = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

function decodeString(value) {
  if (value[0] === 0 && value.length % 2 === 1) return value.subarray(1).toString('utf16le');
  if (value[0] === 1) return value.subarray(1).toString('latin1');
  throw new Error('Unsupported Chromium string encoding');
}

function encodeString(text, marker) {
  if (marker === 1 && [...text].some(c => c.charCodeAt(0) > 255)) marker = 0;
  assert([0, 1].includes(marker));
  return Buffer.concat([Buffer.from([marker]), Buffer.from(text, marker === 0 ? 'utf16le' : 'latin1')]);
}

function validateName(value) {
  if (typeof value !== 'string' || !value || ['__proto__', 'constructor', 'prototype'].includes(value)) {
    throw new Error('An explicit valid profile UID and group name are required');
  }
}

function editState(original, profile, group, url) {
  validateName(profile);
  validateName(group);
  if (!isObject(original) || !owns(original, profile) || !isObject(original[profile])) {
    throw new Error('Profile state missing or unsupported; verify the active profile and visit its proxy page first');
  }
  const before = owns(original[profile], group) ? original[profile][group] : undefined;
  if (before !== undefined && !isObject(before)) throw new Error('Unsupported group state');
  const result = structuredClone(original);
  result[profile][group] = {
    ...(before || {open: false, showType: true, sortType: 0, filterText: '', textState: null, testUrl: ''}),
    testUrl: url
  };
  const restored = structuredClone(result);
  if (before === undefined) delete restored[profile][group];
  else restored[profile][group] = before;
  assert.deepEqual(restored, original, 'Unexpected change outside selected group');
  return result;
}

function isTargetKey(key) {
  const boundary = key.indexOf(0);
  if (boundary < 0 || key.subarray(0, boundary).toString('utf8') !== ORIGIN) return false;
  try { return decodeString(key.subarray(boundary + 1)) === FIELD; }
  catch { return false; }
}

function validateURL(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error('Invalid latency-test URL'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error('Use a plain HTTP(S) test URL without credentials, query parameters or fragments');
  }
  return url.href;
}

function displayURL(value) {
  if (!value) return '';
  try { const u = new URL(value); return u.origin + u.pathname; }
  catch { return '[invalid URL]'; }
}

function backupDatabase(database, destination, key, value) {
  if (!destination) throw new Error('An empty, private --backup directory is required');
  const backup = path.resolve(destination);
  const requestedRelative = path.relative(database, backup);
  if (!requestedRelative || (!requestedRelative.startsWith('..' + path.sep) && requestedRelative !== '..' && !path.isAbsolute(requestedRelative))) {
    throw new Error('Backup must be outside the database directory');
  }
  fs.mkdirSync(backup, {recursive: true, mode: 0o700});
  const canonical = fs.realpathSync(backup);
  const relative = path.relative(database, canonical);
  if (!relative || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative))) {
    throw new Error('Backup must be outside the database directory');
  }
  if (fs.readdirSync(canonical).length) throw new Error('Backup directory is not empty');
  if (process.platform !== 'win32') fs.chmodSync(canonical, 0o700);
  const copy = path.join(canonical, 'leveldb');
  fs.mkdirSync(copy, {mode: 0o700});
  for (const entry of fs.readdirSync(database, {withFileTypes: true})) {
    if (entry.isFile() && !['LOCK', 'LOG', 'LOG.old'].includes(entry.name)) {
      fs.copyFileSync(path.join(database, entry.name), path.join(copy, entry.name), fs.constants.COPYFILE_EXCL);
    }
  }
  fs.writeFileSync(path.join(canonical, 'record-private.json'),
    JSON.stringify({key: key.toString('base64'), value: value.toString('base64')}), {flag: 'wx', mode: 0o600});
  return canonical;
}

async function repairDatabase(options) {
  validateName(options.profile);
  validateName(options.group);
  const url = validateURL(options.url || DEFAULT_URL);
  const database = fs.realpathSync(options.database);
  if (!fs.statSync(database).isDirectory()) throw new Error('Database directory is required');
  if (!['inspect', 'patch'].includes(options.mode)) throw new Error('Mode must be inspect or patch');
  const {ClassicLevel} = require('classic-level');
  const db = new ClassicLevel(database, {keyEncoding: 'buffer', valueEncoding: 'buffer', createIfMissing: false});
  await db.open(); // Exclusive LevelDB lock. Do not bypass a running application's lock.
  try {
    const entries = await db.iterator().all();
    const matches = entries.filter(([key]) => isTargetKey(key));
    if (matches.length !== 1) throw new Error('Expected one known Clash Verge origin and proxy-head-state record');
    const [key, value] = matches[0];
    let original;
    try { original = JSON.parse(decodeString(value)); }
    catch { throw new Error('Invalid or unsupported proxy-head-state record'); }
    const desired = editState(original, options.profile, options.group, url);
    const previous = original[options.profile][options.group]?.testUrl || '';
    const summary = {profile: options.profile, group: options.group, testUrl: displayURL(previous)};
    if (options.mode === 'inspect') return {status: 'inspected', ...summary};
    if (previous === url) return {status: 'already_configured', ...summary, otherRecordsUnchanged: true};
    const backup = backupDatabase(database, options.backup, key, value);
    let written = false;
    try {
      await db.put(key, encodeString(JSON.stringify(desired), value[0]), {sync: true});
      written = true;
      const after = await db.iterator().all();
      assert.equal(after.length, entries.length);
      const index = new Map(after.map(([k, v]) => [k.toString('hex'), v]));
      for (const [k, v] of entries) {
        if (!k.equals(key)) assert(v.equals(index.get(k.toString('hex'))), 'Unrelated record changed');
      }
      assert.deepEqual(JSON.parse(decodeString(await db.get(key))), desired);
    } catch (error) {
      if (written) await db.put(key, value, {sync: true});
      throw error;
    }
    return {status: 'patched', ...summary, testUrl: url, backup, otherRecordsUnchanged: true};
  } finally { await db.close(); }
}

function parseArguments(argv) {
  if (argv.length === 1 && ['--help', '-h'].includes(argv[0])) return null;
  const [mode, ...rest] = argv;
  const options = {mode};
  const fields = new Set(['database', 'profile', 'group', 'url', 'backup']);
  for (let i = 0; i < rest.length; i += 2) {
    const field = rest[i].replace(/^--/, '');
    if (!rest[i].startsWith('--') || !fields.has(field) || !rest[i + 1] || owns(options, field)) {
      throw new Error('Use named --database, --profile, --group and optional --url / --backup arguments');
    }
    options[field] = rest[i + 1];
  }
  if (!options.database) throw new Error('--database is required');
  return options;
}

module.exports = {decodeString, encodeString, editState, repairDatabase};
if (require.main === module) {
  (async () => {
    const options = parseArguments(process.argv.slice(2));
    if (!options) {
      console.log('inspect|patch --database PATH --profile UID --group NAME [--url URL] [--backup PRIVATE_EMPTY_DIR]');
      return;
    }
    console.log(JSON.stringify(await repairDatabase(options)));
  })().catch(error => {
    const message = error.code === 'LEVEL_LOCKED'
      ? 'Database is in use. Close the identified Clash Verge GUI and wait for its WebView to release the lock.'
      : error.message;
    console.error(JSON.stringify({status: 'error', message}));
    process.exitCode = 1;
  });
}
