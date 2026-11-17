<script lang="ts">
	import './layout.css';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import Icon from '#lib/components/Icon.svelte';
	import Leprechaun from '#lib/components/Leprechaun.svelte';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();
	const shell = $derived(data.shell);
	const b = $derived(shell.branding);

	// Only plain hex colours from the tenant config reach the stylesheet.
	const hex = (v: string, fallback: string) => (/^#[0-9a-fA-F]{6}$/.test(v) ? v : fallback);
	const brandCss = $derived(
		`<style>:root{--primary:${hex(b.primary, '#3b7084')};--accent:${hex(b.accent, '#bdcf1f')}}</style>`
	);

	let dark = $state(false);

	function applyTheme(isDark: boolean) {
		dark = isDark;
		document.documentElement.dataset.theme = isDark ? 'dark' : 'light';
	}

	function toggleTheme() {
		applyTheme(!dark);
		try {
			localStorage.setItem('heinzel.theme', dark ? 'dark' : 'light');
		} catch {
			/* storage may be unavailable */
		}
	}

	onMount(() => {
		let stored: string | null = null;
		try {
			stored = localStorage.getItem('heinzel.theme');
		} catch {
			/* ignore */
		}
		const pref = stored ?? b.theme_default;
		applyTheme(
			pref === 'dark' ||
				(pref === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
		);
	});

	const isActive = (path: string) =>
		path === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(path);
</script>

<svelte:head>
	<title>{b.display_name}</title>
	{@html brandCss}
	{#if b.logo_mark}<link rel="icon" href={b.logo_mark} />{/if}
</svelte:head>

<div class="app">
	<aside class="side">
		<a class="brand" href="/" title="Zur Übersicht">
			<img class="logo-light" src={b.logo_light} alt={b.display_name} />
			{#if b.logo_dark}<img class="logo-dark" src={b.logo_dark} alt={b.display_name} />{/if}
		</a>

		<button class="search" type="button" aria-disabled="true" title="Suche folgt">
			<Icon name="search" size={18} />
			<span>Suchen</span>
			<kbd>Ctrl K</kbd>
		</button>

		<nav aria-label="Hauptnavigation">
			{#each shell.navigation as section (section.key)}
				{#if section.label}<div class="area">{section.label}</div>{/if}
				{#each section.items as item (item.key)}
					<a
						class="nav"
						class:on={isActive(item.path)}
						href={item.path}
						aria-current={isActive(item.path) ? 'page' : undefined}
					>
						<Icon name={item.icon} />{item.label}
					</a>
					{#if item.children.length && isActive(item.path)}
						<div class="sub">
							{#each item.children as child (child.key)}
								<a class="subn" class:on={page.url.pathname === child.path} href={child.path}
									>{child.label}</a
								>
							{/each}
						</div>
					{/if}
				{/each}
			{/each}
		</nav>

		<div class="grow"></div>
		<button class="nav" type="button" onclick={toggleTheme}>
			<Icon name="moon" />{dark ? 'Hellmodus' : 'Dunkelmodus'}
		</button>
		{#if b.powered_by}
			<div class="powered"><Leprechaun />powered by <strong>Heinzel</strong></div>
		{/if}
	</aside>

	<main class="main">
		{@render children()}
	</main>
</div>

<style>
	.app {
		display: flex;
		flex-wrap: wrap;
		min-height: 100vh;
		background: var(--bg);
	}
	.side {
		flex: 1 1 248px;
		box-sizing: border-box;
		background: var(--side);
		border-right: 1px solid var(--line);
		padding: 20px 14px;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.main {
		flex: 999 1 560px;
		min-width: 0;
		padding: 36px 40px 48px;
		box-sizing: border-box;
	}
	.brand {
		display: block;
		padding: 6px 10px 18px;
		border-radius: 10px;
	}
	.brand img {
		height: 44px;
		width: auto;
	}
	.search {
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: 44px;
		padding: 0 10px 0 12px;
		margin: 0 2px 12px;
		border: 1px solid var(--input);
		border-radius: 10px;
		background: var(--surface);
		color: var(--muted);
		font: inherit;
		font-size: 15px;
		cursor: pointer;
	}
	.search span {
		flex: 1;
		text-align: left;
	}
	kbd {
		font: 600 11px inherit;
		color: var(--muted-2);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 2px 6px;
		background: var(--surface-2);
	}
	nav {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.area {
		font-size: 12px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--muted-2);
		padding: 18px 12px 6px;
	}
	.nav {
		display: flex;
		align-items: center;
		gap: 12px;
		min-height: 44px;
		padding: 0 12px;
		border: 0;
		border-radius: 10px;
		background: transparent;
		color: var(--ink-2);
		text-decoration: none;
		font: inherit;
		font-size: 15px;
		font-weight: 500;
		cursor: pointer;
		text-align: left;
	}
	.nav:hover {
		background: var(--line-2);
		color: var(--ink);
	}
	.nav.on {
		background: var(--primary-tint);
		color: var(--primary-strong);
		font-weight: 600;
		box-shadow: inset 3px 0 0 var(--accent);
	}
	.sub {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 2px 0 6px 21px;
		padding-left: 10px;
		border-left: 1px solid var(--line);
	}
	.subn {
		display: flex;
		align-items: center;
		min-height: 40px;
		padding: 0 12px;
		border-radius: 8px;
		color: var(--ink-2);
		text-decoration: none;
		font-size: 14px;
	}
	.subn.on {
		background: var(--primary-tint);
		color: var(--primary-strong);
		font-weight: 600;
	}
	.grow {
		flex: 1;
		min-height: 24px;
	}
	.powered {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 12px 12px 0;
		font-size: 12px;
		color: var(--muted-2);
	}
	.powered strong {
		color: var(--ink-2);
	}
</style>
