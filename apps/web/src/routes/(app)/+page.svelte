<script lang="ts">
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const quickActions = $derived(data.shell.quick_actions);
	const firstName = $derived(data.shell.user?.display_name.split(' ')[0] ?? '');
	const inbox = $derived(data.inbox);
</script>

<div class="page">
	<header>
		<h1>Grüezi {firstName}</h1>
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

	{#if inbox}
		<section aria-labelledby="ib-h">
			<h2 id="ib-h">
				Mein Eingang{#if inbox.counts.open}&nbsp;· {inbox.counts.open} offen{/if}
			</h2>
			{#if inbox.items.length}
				<ul class="inbox card">
					{#each inbox.items as i (i.id)}
						<li>
							<a href="/eingang?eintrag={i.id}" class:unread={!i.read}>
								<span class="src"
									>{i.source_label} · {i.kind === 'task' ? 'Aufgabe' : 'Mitteilung'}</span
								>
								<span class="t">{i.title}</span>
							</a>
						</li>
					{/each}
				</ul>
				<a class="all" href="/eingang">Alles in Mein Eingang</a>
			{:else}
				<p class="hint">Nichts offen. Neue Aufgaben und Mitteilungen erscheinen hier.</p>
			{/if}
		</section>
	{/if}
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
	.inbox {
		list-style: none;
		margin: 0;
		padding: 6px;
		max-width: 720px;
	}
	.inbox a {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 10px 12px;
		border-radius: 10px;
		color: var(--ink);
		text-decoration: none;
	}
	.inbox a:hover {
		background: var(--hover);
	}
	.inbox .src {
		font-size: 12px;
		font-weight: 600;
		color: var(--muted-2);
	}
	.inbox .unread .t {
		font-weight: 700;
	}
	.all {
		display: inline-block;
		margin-top: 10px;
		font-size: 14px;
		font-weight: 600;
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
