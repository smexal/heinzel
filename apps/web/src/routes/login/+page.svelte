<script lang="ts">
	import { goto, invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, post, safeNext } from '#lib/api.ts';
	import Leprechaun from '#lib/components/Leprechaun.svelte';
	import type { PageProps } from './$types';

	type Step = 'credentials' | 'totp' | 'mfa_setup';
	type Setup = { secret: string; otpauth_uri: string; qr_svg: string };

	let { data }: PageProps = $props();
	const b = $derived(data.shell.branding);

	let step = $state<Step>('credentials');
	let email = $state('');
	let password = $state('');
	let code = $state('');
	let setup = $state<Setup | null>(null);
	let busy = $state(false);
	let message = $state('');

	const messages: Record<string, string> = {
		invalid_credentials:
			'E-Mail oder Passwort stimmt nicht. Nach mehreren Fehlversuchen wird das Konto kurz gesperrt.',
		invalid_code: 'Der Code stimmt nicht. Bitte den aktuellen Code aus der App eingeben.',
		local_login_disabled: 'Die Anmeldung mit Passwort ist für diese Organisation deaktiviert.',
		not_authenticated: 'Die Anmeldung ist abgelaufen. Bitte erneut anmelden.',
		cross_origin: 'Die Anfrage wurde aus Sicherheitsgründen abgelehnt.'
	};

	async function run(action: () => Promise<void>) {
		busy = true;
		message = '';
		try {
			await action();
		} catch (e) {
			const detail = e instanceof ApiError ? e.detail : 'network';
			message = messages[detail] ?? 'Etwas ist schiefgelaufen. Bitte später erneut versuchen.';
			if (detail === 'not_authenticated') reset();
		} finally {
			busy = false;
		}
	}

	function reset() {
		step = 'credentials';
		code = '';
		setup = null;
	}

	async function next(n: 'done' | 'totp' | 'mfa_setup') {
		code = '';
		if (n === 'done') {
			await invalidateAll();
			await goto(safeNext(page.url.searchParams.get('next')), { replaceState: true });
			return;
		}
		step = n;
		if (n === 'mfa_setup') setup = await post<Setup>('/auth/mfa/setup');
	}

	const submitCredentials = (e: SubmitEvent) => {
		e.preventDefault();
		run(async () => {
			const r = await post<{ next: Step | 'done' }>('/auth/login', { email, password });
			password = '';
			await next(r.next as 'done' | 'totp' | 'mfa_setup');
		});
	};

	const submitCode = (e: SubmitEvent) => {
		e.preventDefault();
		run(async () => {
			const path = step === 'totp' ? '/auth/totp' : '/auth/mfa/confirm';
			await post(path, { code: code.replace(/\s/g, '') });
			await next('done');
		});
	};

	const grouped = (secret: string) => secret.match(/.{1,4}/g)?.join(' ') ?? secret;
</script>

<svelte:head><title>Anmelden · {b.display_name}</title></svelte:head>

<div class="wrap">
	<main class="card">
		<img class="logo logo-light" src={b.logo_light} alt={b.display_name} />
		{#if b.logo_dark}<img class="logo logo-dark" src={b.logo_dark} alt={b.display_name} />{/if}

		{#if step === 'credentials'}
			<h1>Anmelden</h1>
			<form onsubmit={submitCredentials}>
				<label>
					<span>E-Mail</span>
					<input type="email" autocomplete="username" required bind:value={email} disabled={busy} />
				</label>
				<label>
					<span>Passwort</span>
					<input
						type="password"
						autocomplete="current-password"
						required
						bind:value={password}
						disabled={busy}
					/>
				</label>
				{#if message}<p class="msg" role="alert">{message}</p>{/if}
				<button class="primary" type="submit" disabled={busy}>Weiter</button>
			</form>
		{:else}
			{#if step === 'totp'}
				<h1>Bestätigungscode</h1>
				<p class="lead">Gib den 6-stelligen Code aus deiner Authenticator-App ein.</p>
			{:else}
				<h1>Zwei-Faktor einrichten</h1>
				<p class="lead">
					Scanne den QR-Code mit einer Authenticator-App (z. B. Microsoft Authenticator) und gib
					danach den angezeigten Code ein.
				</p>
				{#if setup}
					<img class="qr" src={setup.qr_svg} alt="QR-Code für die Authenticator-App" />
					<details>
						<summary>Code kann nicht gescannt werden?</summary>
						<p>Schlüssel manuell eingeben:</p>
						<code>{grouped(setup.secret)}</code>
					</details>
				{/if}
			{/if}
			<form onsubmit={submitCode}>
				<label>
					<span>Code</span>
					<input
						class="code"
						inputmode="numeric"
						autocomplete="one-time-code"
						pattern={'[0-9 ]{6,7}'}
						maxlength="7"
						required
						bind:value={code}
						disabled={busy}
					/>
				</label>
				{#if message}<p class="msg" role="alert">{message}</p>{/if}
				<button class="primary" type="submit" disabled={busy}>Bestätigen</button>
				<button class="link" type="button" onclick={reset} disabled={busy}>Zurück</button>
			</form>
		{/if}
	</main>

	{#if b.powered_by}
		<div class="powered"><Leprechaun />powered by <strong>Heinzel</strong></div>
	{/if}
</div>

<style>
	.wrap {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 20px;
		padding: 24px;
		box-sizing: border-box;
		background: var(--bg);
	}
	.card {
		width: 100%;
		max-width: 400px;
		box-sizing: border-box;
		padding: 32px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 18px;
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	.logo {
		height: 48px;
		width: auto;
		align-self: flex-start;
		margin-bottom: 8px;
	}
	h1 {
		margin: 0;
		font-size: 24px;
		letter-spacing: -0.01em;
	}
	.lead {
		margin: 0;
		color: var(--muted);
		font-size: 15px;
	}
	form {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-size: 14px;
		font-weight: 600;
		color: var(--ink-2);
	}
	input {
		min-height: 44px;
		padding: 0 12px;
		border: 1px solid var(--input);
		border-radius: 10px;
		background: var(--surface);
		color: var(--ink);
		font: inherit;
		font-size: 16px;
	}
	input:focus-visible {
		outline: 2px solid var(--primary);
		outline-offset: 1px;
	}
	.code {
		font-size: 22px;
		letter-spacing: 0.3em;
		font-variant-numeric: tabular-nums;
	}
	.qr {
		width: 200px;
		height: 200px;
		align-self: center;
		background: #fff;
		border-radius: 12px;
		padding: 6px;
	}
	details {
		font-size: 14px;
		color: var(--muted);
	}
	summary {
		cursor: pointer;
	}
	details code {
		display: block;
		margin-top: 6px;
		padding: 8px 10px;
		border-radius: 8px;
		background: var(--surface-2);
		color: var(--ink);
		font-size: 15px;
		letter-spacing: 0.08em;
		word-break: break-all;
	}
	.msg {
		margin: 0;
		padding: 10px 12px;
		border-radius: 10px;
		background: var(--danger-bg);
		color: var(--danger-ink);
		font-size: 14px;
	}
	.primary {
		min-height: 46px;
		border: 0;
		border-radius: 10px;
		background: var(--primary);
		color: #fff;
		font: inherit;
		font-size: 15px;
		font-weight: 600;
		cursor: pointer;
	}
	.primary:hover {
		background: var(--primary-hover);
	}
	.primary:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.link {
		min-height: 40px;
		border: 0;
		background: transparent;
		color: var(--link);
		font: inherit;
		font-size: 14px;
		cursor: pointer;
	}
	.powered {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12px;
		color: var(--muted-2);
	}
	.powered strong {
		color: var(--ink-2);
	}
</style>
