'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(`${__dirname}/osc52-write.js`, 'utf8');
for (const forbidden of [
  'navigator.clipboard', 'readText(', 'localStorage', 'sessionStorage',
  'fetch(', 'XMLHttpRequest', 'WebSocket', 'console.',
]) {
  assert.equal(source.includes(forbidden), false, `forbidden browser surface: ${forbidden}`);
}

function harness(copyResult = true) {
  let handler;
  let registrations = 0;
  let focusCalls = 0;
  let copyCalls = 0;
  let copiedText = null;
  let currentTextarea = null;
  let throwOnCopy = false;

  const term = {
    focus() { focusCalls += 1; },
    parser: {
      registerOscHandler(identifier, callback) {
        assert.equal(identifier, 52);
        registrations += 1;
        handler = callback;
        return { dispose() {} };
      },
    },
  };
  const document = {
    body: {
      appendChild(element) {
        assert.equal(currentTextarea, null);
        currentTextarea = element;
      },
    },
    createElement(name) {
      assert.equal(name, 'textarea');
      return {
        value: '',
        style: {},
        setAttribute() {},
        focus() {},
        select() {},
        setSelectionRange(start, end) {
          assert.equal(start, 0);
          assert.equal(end, this.value.length);
        },
        remove() {
          assert.equal(this.value, '');
          currentTextarea = null;
        },
      };
    },
    execCommand(command) {
      assert.equal(command, 'copy');
      copyCalls += 1;
      copiedText = currentTextarea.value;
      if (throwOnCopy) throw new Error('synthetic copy failure');
      return copyResult;
    },
  };
  const window = {};
  const context = vm.createContext({
    TextDecoder,
    Uint8Array,
    atob,
    btoa,
    document,
    Symbol,
    window,
  });
  vm.runInContext(source, context);
  window.term = term;

  return {
    emit(data) { return handler(data); },
    rerun() { vm.runInContext(source, context); },
    setThrowOnCopy(value) { throwOnCopy = value; },
    stats() { return { registrations, focusCalls, copyCalls, copiedText, currentTextarea }; },
  };
}

function osc(selector, text) {
  return `${selector};${Buffer.from(text, 'utf8').toString('base64')}`;
}

{
  const test = harness();
  assert.equal(test.emit(osc('', 'empty selector')), true);
  assert.equal(test.emit(osc('c', 'c selector')), true);
  assert.equal(test.stats().copyCalls, 2);
  assert.equal(test.stats().copiedText, 'c selector');
}

{
  const test = harness();
  for (const rejected of ['p;QQ==', ';?', 'c;?', ';not base64', 'c;AA=A', 'c;AB==', 'missing-separator']) {
    assert.equal(test.emit(rejected), true);
  }
  assert.equal(test.stats().copyCalls, 0);
}

{
  const test = harness();
  assert.equal(test.emit('c;wA=='), true);
  assert.equal(test.stats().copyCalls, 0);
  assert.equal(test.stats().currentTextarea, null);
  assert.equal(test.stats().focusCalls, 1);
}

{
  const test = harness();
  const fixture = 'cafe\u0301 pingüino Ω λ 漢字 🚀\nsecond line\n' + 'wrapped-'.repeat(40);
  assert.equal(test.emit(osc('', fixture)), true);
  assert.equal(test.stats().copiedText, fixture);
  assert.equal(test.stats().currentTextarea, null);
  assert.equal(test.stats().focusCalls, 1);
}

{
  const test = harness();
  assert.equal(test.emit(`c;${Buffer.alloc(100001, 65).toString('base64')}`), true);
  assert.equal(test.stats().copyCalls, 0);
}

{
  const test = harness(false);
  assert.equal(test.emit(osc('c', 'copy false')), true);
  assert.deepEqual(test.stats(), {
    registrations: 1,
    focusCalls: 1,
    copyCalls: 1,
    copiedText: 'copy false',
    currentTextarea: null,
  });
}

{
  const test = harness();
  test.setThrowOnCopy(true);
  assert.equal(test.emit(osc('', 'synthetic failure')), true);
  assert.equal(test.stats().currentTextarea, null);
  assert.equal(test.stats().focusCalls, 1);
}

{
  const test = harness();
  test.rerun();
  assert.equal(test.stats().registrations, 1);
  assert.equal(test.emit(osc('', 'after reconnect')), true);
  assert.equal(test.stats().copyCalls, 1);
}

console.log('OK ttyd OSC 52 write-only handler contract');
