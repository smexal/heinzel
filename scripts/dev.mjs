#!/usr/bin/env node
// Development: infrastructure in Docker, API and web on the host with hot reload.
//
//   pnpm dev            start everything (Ctrl+C stops API and web; containers keep running)
//   pnpm dev --no-docker  skip `docker compose up` (Postgres etc. already running)
//
// Steps: docker compose up (postgres, valkey, mailpit) → uv sync → migrate → seed tenants
// → API on :8000 and web on :5173 in parallel, output prefixed with [api] / [web].

import { spawn, spawnSync } from 'node:child_process';
import { copyFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const api = join(root, 'apps', 'api');
const isWin = process.platform === 'win32';
const args = new Set(process.argv.slice(2));

const colour = { api: '\x1b[36m', web: '\x1b[35m', dev: '\x1b[33m' };
const say = (msg) => console.log(`${colour.dev}[dev]\x1b[0m ${msg}`);

function run(cmd, cwd = root) {
	say(cmd);
	const r = spawnSync(cmd, { cwd, stdio: 'inherit', shell: true });
	if (r.status !== 0) {
		say(`failed: ${cmd}`);
		process.exit(r.status ?? 1);
	}
}

function need(tool, hint) {
	const r = spawnSync(isWin ? `where ${tool}` : `command -v ${tool}`, { shell: true });
	if (r.status !== 0) {
		say(`${tool} not found. ${hint}`);
		process.exit(1);
	}
}

need('uv', 'Install: https://docs.astral.sh/uv/ (Windows: winget install astral-sh.uv)');
need('pnpm', 'Install: npm install -g pnpm');

if (!existsSync(join(root, '.env'))) {
	copyFileSync(join(root, '.env.example'), join(root, '.env'));
	say('created .env from .env.example');
}

if (!args.has('--no-docker')) {
	need(
		'docker',
		'Install Docker Desktop, or start the infrastructure yourself and use --no-docker'
	);
	run('docker compose up -d --wait postgres valkey mailpit');
}
run('uv sync', api);
run('uv run heinzel migrate', api);
run('uv run heinzel seed-tenants', api);
if (!existsSync(join(root, 'node_modules'))) run('pnpm install');

const children = [];

function start(name, cmd, cwd) {
	const child = spawn(cmd, { cwd, shell: true, stdio: ['ignore', 'pipe', 'pipe'] });
	const prefix = `${colour[name]}[${name}]\x1b[0m `;
	for (const stream of [child.stdout, child.stderr]) {
		let buf = '';
		stream.on('data', (chunk) => {
			buf += chunk;
			const lines = buf.split(/\r?\n/);
			buf = lines.pop() ?? '';
			for (const line of lines) console.log(prefix + line);
		});
	}
	child.on('exit', (code) => {
		say(`${name} exited (${code ?? 'signal'})`);
		stop(code ?? 0);
	});
	children.push(child);
}

let stopping = false;
function stop(code = 0) {
	if (stopping) return;
	stopping = true;
	for (const child of children) {
		if (child.exitCode !== null) continue;
		// shell: true wraps the process; kill the whole tree.
		if (isWin) spawnSync(`taskkill /pid ${child.pid} /T /F`, { shell: true, stdio: 'ignore' });
		else child.kill('SIGTERM');
	}
	setTimeout(() => process.exit(code), 300);
}

process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));

start('api', 'uv run uvicorn heinzel_api.main:app --reload --port 8000', api);
start('web', 'pnpm --filter web dev', root);
say(
	'web: http://localhost:5173 · API docs: http://localhost:8000/docs · mail: http://localhost:8025'
);
say(
	'first admin: cd apps/api && uv run heinzel create-admin --tenant schmelzi --email … --name "…"'
);
