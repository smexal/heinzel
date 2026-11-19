<script lang="ts">
	import { ApiError, post } from '#lib/api.ts';
	import AuthCard from '#lib/components/AuthCard.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const b = $derived(data.shell.branding);

	let email = $state('');
	let busy = $state(false);
	let sent = $state(false);
	let message = $state('');

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		busy = true;
		message = '';
		try {
			await post('/auth/password/forgot', { email });
			sent = true;
		} catch (err) {
			message =
				err instanceof ApiError && err.detail === 'rate_limited'
					? 'Zu viele Anfragen. Bitte versuche es in einigen Minuten erneut.'
					: 'Etwas ist schiefgelaufen. Bitte später erneut versuchen.';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>Passwort vergessen · {b.display_name}</title></svelte:head>

<AuthCard branding={b}>
	<h1>Passwort vergessen</h1>
	{#if sent}
		<p class="notice ok" role="status">
			Wenn ein Konto mit <strong>{email}</strong> existiert, ist eine E-Mail mit einem Link unterwegs.
			Der Link ist eine Stunde gültig.
		</p>
		<a class="btn btn-secondary" href="/login">Zur Anmeldung</a>
	{:else}
		<p class="lead">
			Gib deine E-Mail-Adresse ein. Wir senden dir einen Link für ein neues Passwort.
		</p>
		<form onsubmit={submit}>
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
			{#if message}<p class="notice error" role="alert">{message}</p>{/if}
			<button class="btn btn-primary" type="submit" disabled={busy} aria-busy={busy}
				>Link senden</button
			>
			<a class="btn btn-link" href="/login">Zurück zur Anmeldung</a>
		</form>
	{/if}
</AuthCard>
