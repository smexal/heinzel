<script lang="ts">
	import { goto, invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import { post } from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';
	import Leprechaun from '#lib/components/Leprechaun.svelte';
	import { theme, toggleTheme } from '#lib/theme.svelte.ts';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();
	const shell = $derived(data.shell);
	const b = $derived(shell.branding);
	const user = $derived(shell.user);

	const isActive = (path: string) =>
		path === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(path);

	async function logout() {
		try {
			await post('/auth/logout');
		} finally {
			await invalidateAll();
			await goto('/login');
		}
	}
</script>

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
			<Icon name="moon" />{theme.dark ? 'Hellmodus' : 'Dunkelmodus'}
		</button>
		{#if user}
			<div class="me" class:on={page.url.pathname.startsWith('/profil')}>
				<a class="profile" href="/profil" title="Mein Profil">
					<span class="avatar" aria-hidden="true">{user.initials}</span>
					<span class="who">
						<strong>{user.display_name}</strong>
						<small>{user.email}</small>
					</span>
				</a>
				<button class="out" type="button" onclick={logout} title="Abmelden" aria-label="Abmelden">
					<Icon name="log-out" size={18} />
				</button>
			</div>
		{/if}
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
	.me {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-top: 10px;
		padding: 10px 8px 10px 10px;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: var(--surface);
	}
	.me.on {
		background: var(--primary-tint);
		border-color: transparent;
	}
	.profile {
		display: flex;
		align-items: center;
		gap: 10px;
		flex: 1;
		min-width: 0;
		color: inherit;
		text-decoration: none;
		border-radius: 8px;
	}
	.profile:focus-visible {
		outline: 2px solid var(--primary);
		outline-offset: 2px;
	}
	.avatar {
		display: grid;
		place-items: center;
		flex: none;
		width: 34px;
		height: 34px;
		border-radius: 50%;
		background: var(--primary-tint);
		color: var(--primary-strong);
		font-size: 13px;
		font-weight: 700;
	}
	.who {
		display: flex;
		flex-direction: column;
		min-width: 0;
		flex: 1;
	}
	.who strong,
	.who small {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.who strong {
		font-size: 14px;
		color: var(--ink);
	}
	.who small {
		font-size: 12px;
		color: var(--muted);
	}
	.out {
		display: grid;
		place-items: center;
		flex: none;
		width: 36px;
		height: 36px;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: var(--muted);
		cursor: pointer;
	}
	.out:hover {
		background: var(--line-2);
		color: var(--ink);
	}
</style>
