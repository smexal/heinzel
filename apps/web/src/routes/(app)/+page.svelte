<script lang="ts">
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const quickActions = $derived(data.shell.quick_actions);
</script>

<div class="page">
	<header>
		<h1>Grüezi</h1>
		<p>Willkommen bei {data.shell.branding.display_name}.</p>
	</header>

	<section aria-labelledby="qa-h">
		<h2 id="qa-h">Was möchtest du tun?</h2>
		<div class="grid">
			{#each quickActions as qa (qa.key)}
				<a class="qa" href={qa.path}>{qa.label}</a>
			{:else}
				<p class="hint">Aktionen erscheinen hier, sobald Module aktiviert sind.</p>
			{/each}
		</div>
	</section>
</div>

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: 28px;
		max-width: 1240px;
	}
	h1 {
		margin: 0;
		font-size: 32px;
		letter-spacing: -0.02em;
	}
	header p {
		margin: 6px 0 0;
		color: var(--muted);
	}
	h2 {
		margin: 0 0 12px;
		font-size: 15px;
		font-weight: 600;
		color: var(--muted);
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
		gap: 14px;
	}
	.qa {
		display: flex;
		align-items: center;
		min-height: 64px;
		padding: 0 18px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 14px;
		color: var(--ink);
		text-decoration: none;
		font-weight: 600;
	}
	.qa:hover {
		border-color: var(--primary);
	}
	.hint {
		color: var(--muted);
	}
</style>
