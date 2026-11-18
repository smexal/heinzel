<script lang="ts">
	// Centred card with the tenant logo, used by login, password and invitation pages.
	import type { Snippet } from 'svelte';
	import Leprechaun from '#lib/components/Leprechaun.svelte';
	import type { Shell } from '#lib/shell.ts';

	let { branding, children }: { branding: Shell['branding']; children: Snippet } = $props();
</script>

<div class="wrap">
	<main class="card auth">
		<img class="logo logo-light" src={branding.logo_light} alt={branding.display_name} />
		{#if branding.logo_dark}
			<img class="logo logo-dark" src={branding.logo_dark} alt={branding.display_name} />
		{/if}
		{@render children()}
	</main>
	<footer class="foot">
		{#if branding.imprint_url}<a href={branding.imprint_url} rel="noopener">Impressum</a>{/if}
		{#if branding.privacy_url}<a href={branding.privacy_url} rel="noopener">Datenschutz</a>{/if}
		{#if branding.powered_by}
			<span class="powered"><Leprechaun />powered by <strong>Heinzel</strong></span>
		{/if}
	</footer>
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
	.auth {
		width: 100%;
		max-width: 400px;
		box-sizing: border-box;
		padding: 32px;
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
	.auth :global(h1) {
		margin: 0;
		font-size: 24px;
		letter-spacing: -0.01em;
	}
	.auth :global(.lead) {
		margin: 0;
		color: var(--muted);
		font-size: 15px;
	}
	.auth :global(form) {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	.foot {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: center;
		gap: 8px 18px;
		font-size: 13px;
	}
	.foot a {
		color: var(--muted);
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
