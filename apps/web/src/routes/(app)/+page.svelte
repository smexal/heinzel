<script lang="ts">
	import { formatter } from '#lib/format.ts';
	import Icon from '#lib/components/Icon.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const fmt = $derived(formatter(data.shell.user?.localization));
	const quickActions = $derived(data.shell.quick_actions);
	const firstName = $derived(data.shell.user?.display_name.split(' ')[0] ?? '');
	const inbox = $derived(data.inbox);
	const today = $derived.by(() => {
		const now = new Date();
		const w = fmt.weekday(now);
		return `${w.charAt(0).toUpperCase()}${w.slice(1)}, ${fmt.dayMonth(now)}`;
	});
	const waiting = $derived(inbox?.counts.tasks ?? 0);
	const TONES = ['info', 'ok', 'primary', 'warn'];
</script>

<svelte:head><title>Übersicht · {data.shell.branding.display_name}</title></svelte:head>

<div class="page">
	<header>
		<h1>Grüezi {firstName}</h1>
		<p>
			{today}{waiting
				? ` · ${waiting} ${waiting === 1 ? 'Aufgabe wartet' : 'Aufgaben warten'} auf dich`
				: ''}
		</p>
	</header>

	<section aria-labelledby="qa-h">
		<h2 id="qa-h" class="sec">Was möchtest du tun?</h2>
		<div class="qgrid">
			{#each quickActions as qa, i (qa.key)}
				<a class="qa" href={qa.path}>
					<span class="qi tone-{TONES[i % TONES.length]}"><Icon name={qa.icon} size={22} /></span>
					<span class="qt">
						<span class="ql">{qa.label}</span>
						{#if qa.description}<span class="qd">{qa.description}</span>{/if}
					</span>
				</a>
			{/each}
			<div class="qmore">
				<Icon name="grid" size={22} />
				Weitere Aktionen erscheinen hier, sobald neue Module aktiviert sind.
			</div>
		</div>
	</section>

	<div class="board">
		{#if inbox}
			<section class="card" aria-labelledby="ib-h">
				<div class="ch">
					<h2 id="ib-h">Wartet auf dich</h2>
					<a href="/eingang">Mein Eingang</a>
				</div>
				{#if inbox.items.length}
					<ul class="rows">
						{#each inbox.items as i (i.id)}
							<li>
								<a href="/eingang?eintrag={i.id}" class:unread={!i.read}>
									<span class="chip {i.severity === 'urgent' ? 'danger' : 'info'}"
										>{i.source_label} · {i.kind === 'task' ? 'Aufgabe' : 'Mitteilung'}</span
									>
									<span class="t">{i.title}</span>
									{#if i.context}<span class="m">{i.context}</span>{/if}
								</a>
							</li>
						{/each}
					</ul>
				{:else}
					<p class="empty">Nichts offen. Neue Aufgaben und Mitteilungen erscheinen hier.</p>
				{/if}
			</section>
		{/if}

		{#if data.widgets.length}
			<div class="widgets">
				{#each data.widgets as w (w.module + w.key)}
					<section class="card" aria-labelledby="w-{w.key}">
						<div class="ch">
							<div class="wt">
								<span class="eyebrow">{w.eyebrow}</span>
								<h2 id="w-{w.key}">{w.title}</h2>
							</div>
							{#if w.link}<a href={w.link}>{w.link_label ?? 'Öffnen'}</a>{/if}
						</div>
						{#if w.items.length}
							<ul class="witems">
								{#each w.items as it, k (k)}
									<li>
										<a href={it.href ?? w.link ?? '#'}>
											<span class="box" aria-hidden="true"></span>
											<span class="wtx">
												<span class="t">{it.title}</span>
												{#if it.meta}<span class="m" class:danger={it.tone === 'danger'}
														>{it.meta}</span
													>{/if}
											</span>
										</a>
									</li>
								{/each}
							</ul>
						{:else}
							<p class="empty">{w.empty}</p>
						{/if}
					</section>
				{/each}
			</div>
		{/if}
	</div>
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
		font-size: 16px;
	}
	.sec {
		margin: 0 0 12px;
		color: var(--muted);
		font-size: 15px;
		font-weight: 600;
	}
	.qgrid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
		gap: 14px;
	}
	.qa {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 18px;
		border: 1px solid var(--line);
		border-radius: 14px;
		background: var(--surface);
		color: var(--ink);
		text-decoration: none;
	}
	.qa:hover {
		border-color: var(--primary);
	}
	.qi {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: 44px;
		height: 44px;
		border-radius: 12px;
	}
	.tone-info {
		background: var(--info-bg);
		color: var(--info-ink);
	}
	.tone-ok {
		background: var(--ok-bg);
		color: var(--ok-ink);
	}
	.tone-primary {
		background: var(--primary-tint);
		color: var(--primary-strong);
	}
	.tone-warn {
		background: var(--warn-bg);
		color: var(--warn-ink);
	}
	.qt {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.ql {
		font-size: 16px;
		font-weight: 600;
	}
	.qd {
		color: var(--muted);
		font-size: 14px;
	}
	.qmore {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 18px;
		border: 1.5px dashed var(--input);
		border-radius: 14px;
		color: var(--muted);
		font-size: 14px;
		line-height: 1.45;
	}
	.board {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
		align-items: start;
		gap: 20px;
	}
	.widgets {
		display: flex;
		flex-direction: column;
		gap: 20px;
	}
	.ch {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 18px 22px;
		border-bottom: 1px solid var(--line-2);
	}
	.ch h2 {
		margin: 0;
		font-size: 18px;
	}
	.ch a {
		font-size: 14px;
		font-weight: 600;
	}
	.wt {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.eyebrow {
		color: var(--muted-2);
		font-size: 12px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}
	.rows,
	.witems {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.rows li + li,
	.witems li + li {
		border-top: 1px solid var(--line-3);
	}
	.rows a {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 6px;
		padding: 16px 22px;
		color: var(--ink);
		text-decoration: none;
	}
	.rows a:hover,
	.witems a:hover {
		background: var(--hover);
	}
	.t {
		font-size: 16px;
		font-weight: 600;
	}
	.rows a:not(.unread) .t {
		font-weight: 500;
	}
	.m {
		color: var(--muted);
		font-size: 14px;
	}
	.m.danger {
		color: var(--danger-ink);
		font-weight: 600;
	}
	.chip.danger {
		background: var(--danger-bg);
		color: var(--danger-ink);
	}
	.witems {
		padding: 6px 0 10px;
	}
	.witems a {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 12px 22px;
		color: var(--ink);
		text-decoration: none;
	}
	.box {
		flex: none;
		width: 20px;
		height: 20px;
		border: 2px solid var(--input);
		border-radius: 6px;
		box-sizing: border-box;
	}
	.wtx {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.witems .t {
		font-size: 15px;
	}
	.witems .m {
		font-size: 13px;
	}
	.empty {
		margin: 0;
		padding: 18px 22px;
		color: var(--muted);
	}
</style>
