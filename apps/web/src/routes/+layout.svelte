<script lang="ts">
	import './layout.css';
	import { onMount } from 'svelte';
	import { navigating } from '$app/state';
	import { initTheme } from '#lib/theme.svelte.ts';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();
	const b = $derived(data.shell.branding);

	// Only plain hex colours from the tenant config reach the stylesheet. `:root:root` outranks
	// the defaults in layout.css regardless of stylesheet order.
	const hex = (v: string, fallback: string) => (/^#[0-9a-fA-F]{6}$/.test(v) ? v : fallback);
	const brandCss = $derived(
		`<style>:root:root{--primary:${hex(b.primary, '#3b7084')};--accent:${hex(b.accent, '#bdcf1f')}}</style>`
	);

	onMount(() => initTheme(b.theme_default));
</script>

<svelte:head>
	<title>{b.display_name}</title>
	{@html brandCss}
	{#if b.logo_mark}<link rel="icon" href={b.logo_mark} />{/if}
</svelte:head>

<!-- Page loads: a thin bar at the top, only when a navigation takes longer than a moment. -->
{#if navigating.to}
	<div class="navbar" role="progressbar" aria-label="Seite wird geladen"></div>
{/if}

{@render children()}

<style>
	.navbar {
		position: fixed;
		inset: 0 0 auto;
		z-index: 1000;
		height: 3px;
		overflow: hidden;
		background: color-mix(in oklab, var(--primary) 20%, transparent);
		animation: hz-fade-in 0.15s 0.2s both;
	}
	.navbar::after {
		content: '';
		position: absolute;
		inset: 0 auto 0 0;
		width: 40%;
		background: var(--primary);
		animation: navbar 1.1s ease-in-out infinite;
	}
	@keyframes navbar {
		from {
			left: -40%;
		}
		to {
			left: 100%;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.navbar::after {
			width: 100%;
			animation: none;
			opacity: 0.6;
		}
	}
</style>
