<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, post } from '#lib/api.ts';
	import AuthCard from '#lib/components/AuthCard.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const b = $derived(data.shell.branding);
	const info = $derived(data.info);
	const invite = $derived(info?.purpose === 'invite');

	let password = $state('');
	let repeat = $state('');
	let busy = $state(false);
	let message = $state('');

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		message = '';
		if (!info) return;
		if (password.length < info.password_min_length) {
			message = `Das Passwort muss mindestens ${info.password_min_length} Zeichen lang sein.`;
			return;
		}
		if (password !== repeat) {
			message = 'Die beiden Passwörter stimmen nicht überein.';
			return;
		}
		busy = true;
		try {
			await post('/auth/password/set', { token: page.params.token, password });
			await goto('/login?passwort=gesetzt', { replace: true });
		} catch (err) {
			const detail = err instanceof ApiError ? err.detail : '';
			message =
				detail === 'invalid_token'
					? 'Dieser Link ist abgelaufen oder wurde bereits verwendet.'
					: detail === 'password_policy'
						? `Das Passwort muss mindestens ${info.password_min_length} Zeichen lang sein.`
						: 'Etwas ist schiefgelaufen. Bitte später erneut versuchen.';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head>
	<title>{invite ? 'Konto einrichten' : 'Neues Passwort'} · {b.display_name}</title>
	<meta name="referrer" content="no-referrer" />
</svelte:head>

<AuthCard branding={b}>
	{#if !info}
		<h1>Link nicht gültig</h1>
		<p class="lead">
			Dieser Link ist abgelaufen oder wurde bereits verwendet. Fordere einen neuen an oder wende
			dich an die Administration.
		</p>
		<a class="btn btn-primary" href="/passwort-vergessen">Neuen Link anfordern</a>
		<a class="btn btn-link" href="/login">Zur Anmeldung</a>
	{:else}
		<h1>{invite ? `Willkommen, ${info.display_name}` : 'Neues Passwort festlegen'}</h1>
		<p class="lead">
			{invite
				? 'Lege ein Passwort für dein Konto fest. Danach richtest du die Zwei-Faktor-Anmeldung ein.'
				: `Für ${info.email}. Danach meldest du dich mit dem neuen Passwort an.`}
		</p>
		<form onsubmit={submit}>
			<input type="email" autocomplete="username" value={info.email} hidden readonly />
			<label class="field">
				<span>Neues Passwort</span>
				<input
					class="input"
					type="password"
					autocomplete="new-password"
					minlength={info.password_min_length}
					required
					bind:value={password}
					disabled={busy}
				/>
				<small
					>Mindestens {info.password_min_length} Zeichen. Ein Satz aus mehreren Wörtern ist gut.</small
				>
			</label>
			<label class="field">
				<span>Passwort wiederholen</span>
				<input
					class="input"
					type="password"
					autocomplete="new-password"
					required
					bind:value={repeat}
					disabled={busy}
				/>
			</label>
			{#if message}<p class="notice error" role="alert">{message}</p>{/if}
			<button class="btn btn-primary" type="submit" disabled={busy}>Passwort speichern</button>
		</form>
	{/if}
</AuthCard>
