<script lang="ts">
	import './layout.css';
	import { onMount } from 'svelte';
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

{@render children()}
