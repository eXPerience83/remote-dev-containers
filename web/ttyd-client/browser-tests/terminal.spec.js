const { test, expect } = require('@playwright/test');
const { execFileSync } = require('node:child_process');

async function terminalText(page) {
  return page.evaluate(() => {
    const buffer = window.term.buffer.active;
    const lines = [];
    for (let index = 0; index < buffer.length; index += 1) {
      lines.push(buffer.getLine(index)?.translateToString(true) ?? '');
    }
    return lines.join('\n');
  });
}

async function expectTerminalText(page, expected) {
  await expect.poll(() => terminalText(page)).toContain(expected);
}

test('stable ttyd client preserves authenticated I/O, Unicode, resize, and options', async ({ page }) => {
  await page.goto('./');
  await page.waitForFunction(() => window.term && window.term.element);
  await expect(page.locator('[data-remote-dev-extensions]')).toHaveCount(1);
  await expect(page.locator('[data-remote-dev-extensions]')).toHaveAttribute('data-connection-state', 'open');

  const terminal = page.locator('.xterm-helper-textarea');
  await terminal.focus();
  await terminal.pressSequentially("printf 'REMOTE_DEV_UNICODE_á中\\n'", { delay: 5 });
  await terminal.press('Enter');
  await expectTerminalText(page, 'REMOTE_DEV_UNICODE_á中');

  await page.evaluate(() => window.term.resize(100, 30));
  await terminal.pressSequentially("printf 'REMOTE_DEV_SIZE_%s\\n' \"$(stty size)\"", { delay: 5 });
  await terminal.press('Enter');
  await expectTerminalText(page, 'REMOTE_DEV_SIZE_30 100');

  const options = await page.evaluate(() => ({
    fontSize: window.term.options.fontSize,
    disableLeaveAlert: window.term.options.disableLeaveAlert,
  }));
  expect(options).toEqual({ fontSize: 15, disableLeaveAlert: false });
});

test('abnormal socket close reconnects without duplicate terminal input', async ({ page }) => {
  await page.goto('./');
  await page.waitForFunction(() => window.term && window.term.element);
  const connectionState = page.locator('[data-remote-dev-extensions]');
  await expect(connectionState).toHaveAttribute('data-connection-state', 'open');
  const terminal = page.locator('.xterm-helper-textarea');
  await terminal.focus();
  await terminal.pressSequentially('stty -echo');
  await terminal.press('Enter');
  execFileSync('docker', [
    'exec', process.env.TTYD_TEST_CONTAINER, 'sh', '-c',
    'kill -9 "$(pgrep -xo ttyd)"',
  ]);
  await expect(connectionState).toHaveAttribute('data-connection-state', 'closed');
  await expect(connectionState).toHaveAttribute('data-connection-state', 'open', { timeout: 15_000 });
  await terminal.focus();
  await terminal.pressSequentially("printf 'REMOTE_DEV_RECONNECT_ONCE\\n'", { delay: 5 });
  await terminal.press('Enter');
  await expectTerminalText(page, 'REMOTE_DEV_RECONNECT_ONCE');
  const text = await terminalText(page);
  expect(text.split('REMOTE_DEV_RECONNECT_ONCE').length - 1).toBe(1);
});

test('renderer failure falls back without losing the terminal', async ({ browser }) => {
  const context = await browser.newContext({
    httpCredentials: { username: 'synthetic', password: 'synthetic-password' },
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    HTMLCanvasElement.prototype.getContext = () => null;
  });
  await page.goto(process.env.TTYD_TEST_URL);
  await page.waitForFunction(() => window.term && window.term.element);
  await expect(page.locator('.xterm-helper-textarea')).toHaveCount(1);
  await context.close();
});
