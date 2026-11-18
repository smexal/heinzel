<script lang="ts">
	import { goto, invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, post, safeNext } from '#lib/api.ts';
	import AuthCard from '#lib/components/AuthCard.svelte';
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
		cross_origin: 'Die Anfrage wurde aus Sicherheitsgründen abgelehnt.',
		rate_limited: 'Zu viele Versuche. Bitte warte einige Minuten und versuche es dann erneut.'
	};

	const done = $derived(page.url.searchParams.get('passwort') === 'gesetzt');

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
			await goto(safeNext(page.url.searchParams.get('next')), { replace: true });
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

<AuthCard branding={b}>
	{#if step === 'credentials'}
		<h1>Anmelden</h1>
		{#if done && !message}
			<p class="notice ok">Dein Passwort ist gesetzt. Melde dich jetzt damit an.</p>
		{/if}
		<form onsubmit={submitCredentials}>
			<label class="field">
				<span>E-Mail</span>
				<input
					class="input"
					type="email"
					autocomplete="username"
					required
					bind:value={email}
					disabled={busy}
				/>
			</label>
			<label class="field">
				<span>Passwort</span>
				<input
					class="input"
					type="password"
					autocomplete="current-password"
					required
					bind:value={password}
					disabled={busy}
				/>
			</label>
			{#if message}<p class="notice error" role="alert">{message}</p>{/if}
			<button class="btn btn-primary" type="submit" disabled={busy}>Weiter</button>
			<a class="forgot" href="/passwort-vergessen">Passwort vergessen?</a>
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
			<label class="field">
				<span>Code</span>
				<input
					class="input code"
					inputmode="numeric"
					autocomplete="one-time-code"
					pattern={'[0-9 ]{6,7}'}
					maxlength="7"
					required
					bind:value={code}
					disabled={busy}
				/>
			</label>
			{#if message}<p class="notice error" role="alert">{message}</p>{/if}
			<button class="btn btn-primary" type="submit" disabled={busy}>Bestätigen</button>
			<button class="btn btn-link" type="button" onclick={reset} disabled={busy}>Zurück</button>
		</form>
	{/if}
</AuthCard>

<style>
	.code {
		font-size: 22px;
		letter-spacing: 0.3em;
		font-variant-numeric: tabular-nums;
	}
	.forgot {
		align-self: center;
		font-size: 14px;
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
</style>
