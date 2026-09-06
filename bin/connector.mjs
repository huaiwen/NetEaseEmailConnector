#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const child = spawn('uv', ['run', '--directory', root, '--locked', '--no-dev',
  'netease-email-connector', ...process.argv.slice(2)], { stdio: 'inherit' });
child.on('error', () => {
  console.error('Cannot start uv. Install uv first: https://docs.astral.sh/uv/getting-started/installation/');
  process.exitCode = 1;
});
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('exit', (code, signal) => { process.exitCode = code ?? (signal ? 1 : 0); });
