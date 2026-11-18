<script lang="ts">
	// Mounted once in the app layout; opened by withStepUp() from #lib/stepup.svelte.ts.
	import { ApiError } from '#lib/api.ts';
	import { cancelStepUp, confirmStepUp, stepUp } from '#lib/stepup.svelte.ts';

	let { mfa }: { mfa: boolean } = $props();

	let dialog: HTMLDialogElement;
	let value = $state('');
	let busy = $state(false);
	let error = $state('');

	$effect(() => {
		if (stepUp.open && !dialog.open) {
			value = '';
			error = '';
			dialog.showModal();
		} else if (!stepUp.open && dialog.open) {
			dialog.close();
		}
	});

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		busy = true;
		error = '';
		try {
			await confirmStepUp(mfa ? { code: value.replace(/\s/g, '') } : { password: value });
		} catch (err) {
			error =
				err instanceof ApiError && err.detail === 'rate_limited'
					? 'Zu viele Versuche. Bitte warte einige Minuten.'
					: mfa
						? 'Der Code stimmt nicht. Gib den aktuellen Code aus der App ein.'
						: 'Das Passwort stimmt nicht.';
		} finally {
			busy = false;
		}
	}
</script>

<dialog
	bind:this={dialog}
	class="card step"
	aria-labelledby="su-h"
	oncancel={(e) => {
		e.preventDefault();
		cancelStepUp();
	}}
>
	<form onsubmit={submit}>
		<h2 id="su-h">Änderung bestätigen</h2>
		<p>
			Änderungen an Rollen und Berechtigungen bestätigst du erneut. Die Bestätigung gilt 10 Minuten.
		</p>
		<label class="field">
			<span>{mfa ? 'Code aus der Authenticator-App' : 'Dein Passwort'}</span>
			{#if mfa}
				<input
					class="input code"
					inputmode="numeric"
					autocomplete="one-time-code"
					maxlength="7"
					required
					bind:value
					disabled={busy}
				/>
			{:else}
				<input
					class="input"
					type="password"
					autocomplete="current-password"
					required
					bind:value
					disabled={busy}
				/>
			{/if}
		</label>
		{#if error}<p class="notice error" role="alert">{error}</p>{/if}
		<div class="buttons">
			<button class="btn btn-secondary" type="button" onclick={cancelStepUp}>Abbrechen</button>
			<button class="btn btn-primary" type="submit" disabled={busy}>Bestätigen</button>
		</div>
	</form>
</dialog>

<style>
	.step {
		margin: auto;
		width: min(420px, calc(100vw - 32px));
		padding: 28px;
		border-radius: 18px;
		color: var(--ink);
		box-sizing: border-box;
	}
	.step::backdrop {
		background: rgb(0 0 0 / 0.35);
	}
	form {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	h2 {
		margin: 0;
		font-size: 22px;
	}
	p {
		margin: 0;
		color: var(--muted);
		font-size: 15px;
	}
	.code {
		font-size: 22px;
		letter-spacing: 0.3em;
		font-variant-numeric: tabular-nums;
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 10px;
	}
</style>
