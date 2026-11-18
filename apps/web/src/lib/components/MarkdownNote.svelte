<script lang="ts">
	// A note with simple Markdown: shown formatted, edited as text in a field that grows with
	// its content. Toolbar and shortcuts (Ctrl+B, Ctrl+I) insert the Markdown; Esc or
	// "Fertig" saves, as does leaving the field.
	import { tick } from 'svelte';
	import { renderMarkdown } from '#lib/markdown.ts';
	import Icon from '#lib/components/Icon.svelte';

	let {
		value,
		label = 'Notiz',
		placeholder = 'Notiz hinzufügen …',
		onsave
	}: {
		value: string;
		label?: string;
		placeholder?: string;
		onsave: (value: string) => void;
	} = $props();

	const uid = $props.id();
	let editing = $state(false);
	let draft = $state('');
	let area = $state<HTMLTextAreaElement>();
	const html = $derived(renderMarkdown(value));

	async function edit() {
		draft = value;
		editing = true;
		await tick();
		grow();
		area?.focus();
		area?.setSelectionRange(draft.length, draft.length);
	}

	function finish() {
		editing = false;
		if (draft !== value) onsave(draft);
	}

	function grow() {
		if (!area) return;
		area.style.height = 'auto';
		area.style.height = `${area.scrollHeight + 2}px`;
	}

	// --- formatting helpers -----------------------------------------------------------------
	async function apply(next: string, selStart: number, selEnd: number) {
		draft = next;
		await tick();
		area?.focus();
		area?.setSelectionRange(selStart, selEnd);
		grow();
	}

	function wrap(mark: string, fallback: string) {
		if (!area) return;
		const { selectionStart: a, selectionEnd: b } = area;
		const sel = draft.slice(a, b) || fallback;
		const next = draft.slice(0, a) + mark + sel + mark + draft.slice(b);
		apply(next, a + mark.length, a + mark.length + sel.length);
	}

	function prefixLines(kind: 'ul' | 'ol') {
		if (!area) return;
		const { selectionStart: a, selectionEnd: b } = area;
		const start = draft.lastIndexOf('\n', a - 1) + 1;
		const endNl = draft.indexOf('\n', b);
		const end = endNl === -1 ? draft.length : endNl;
		const lines = draft.slice(start, end).split('\n');
		const done = lines.map((l, i) => (kind === 'ul' ? `- ${l}` : `${i + 1}. ${l}`)).join('\n');
		apply(
			draft.slice(0, start) + done + draft.slice(end),
			start + done.length,
			start + done.length
		);
	}

	function link() {
		if (!area) return;
		const { selectionStart: a, selectionEnd: b } = area;
		const text = draft.slice(a, b) || 'Linktext';
		const insert = `[${text}](https://)`;
		const urlAt = a + text.length + 3;
		apply(draft.slice(0, a) + insert + draft.slice(b), urlAt, urlAt + 8);
	}

	function keys(e: KeyboardEvent) {
		const mod = e.ctrlKey || e.metaKey;
		if (e.key === 'Escape' || (mod && e.key === 'Enter')) {
			e.preventDefault();
			area?.blur();
		} else if (mod && e.key.toLowerCase() === 'b') {
			e.preventDefault();
			wrap('**', 'fett');
		} else if (mod && e.key.toLowerCase() === 'i') {
			e.preventDefault();
			wrap('*', 'kursiv');
		}
	}

	const keep = (e: MouseEvent) => e.preventDefault(); // toolbar clicks keep the focus
</script>

<div class="note">
	<div class="head">
		<span class="label" id="{uid}-l">{label}</span>
		{#if editing}
			<div class="tools" role="toolbar" aria-label="Formatierung">
				<button
					type="button"
					onmousedown={keep}
					onclick={() => wrap('**', 'fett')}
					title="Fett (Ctrl+B)"><strong>B</strong></button
				>
				<button
					type="button"
					onmousedown={keep}
					onclick={() => wrap('*', 'kursiv')}
					title="Kursiv (Ctrl+I)"><em>I</em></button
				>
				<button type="button" onmousedown={keep} onclick={() => prefixLines('ul')} title="Liste"
					><Icon name="list" size={16} /><span class="sr-only">Liste</span></button
				>
				<button
					type="button"
					onmousedown={keep}
					onclick={() => prefixLines('ol')}
					title="Nummerierte Liste"><span class="num">1.</span></button
				>
				<button type="button" onmousedown={keep} onclick={link} title="Link"
					><Icon name="link" size={16} /><span class="sr-only">Link</span></button
				>
				<button type="button" class="done" onclick={() => area?.blur()}>Fertig</button>
			</div>
		{:else if value}
			<button type="button" class="btn btn-link edit" onclick={edit}>Bearbeiten</button>
		{/if}
	</div>

	{#if editing}
		<textarea
			bind:this={area}
			bind:value={draft}
			class="input area"
			aria-labelledby="{uid}-l"
			aria-describedby="{uid}-h"
			{placeholder}
			oninput={grow}
			onkeydown={keys}
			onblur={finish}></textarea>
		<small id="{uid}-h"
			>**fett**, *kursiv*, - Liste, 1. Liste, [Text](https://…), Zeilenumbruch mit Enter</small
		>
	{:else if value}
		<!-- Rendered from escaped text: renderMarkdown never passes user HTML through. -->
		<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
		<div
			class="md"
			aria-labelledby="{uid}-l"
			onclick={(e) => {
				if (!(e.target as HTMLElement).closest('a')) edit();
			}}
		>
			{@html html}
		</div>
	{:else}
		<button type="button" class="empty" onclick={edit}>{placeholder}</button>
	{/if}
</div>

<style>
	.note {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		min-height: 32px;
	}
	.label {
		color: var(--ink-2);
		font-size: 14px;
		font-weight: 600;
	}
	.edit {
		min-height: 32px;
		padding: 0 4px;
		font-size: 14px;
	}
	.tools {
		display: flex;
		flex-wrap: wrap;
		gap: 2px;
	}
	.tools button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 32px;
		height: 32px;
		padding: 0 8px;
		border: 1px solid transparent;
		border-radius: 6px;
		background: transparent;
		color: var(--ink-2);
		font: inherit;
		font-size: 14px;
		cursor: pointer;
	}
	.tools button:hover {
		background: var(--hover);
	}
	.tools button:focus-visible {
		outline: 2px solid var(--primary);
	}
	.tools .num {
		font-weight: 600;
	}
	.tools .done {
		margin-left: 6px;
		border-color: var(--input);
		font-weight: 600;
	}
	.area {
		min-height: 180px;
		max-height: 60vh;
		padding: 10px 12px;
		font-size: 15px;
		line-height: 1.5;
		resize: vertical;
	}
	small {
		color: var(--muted);
		font-size: 12px;
	}
	.empty {
		min-height: 96px;
		padding: 12px;
		border: 1px dashed var(--input);
		border-radius: 10px;
		background: transparent;
		color: var(--muted);
		font: inherit;
		font-size: 15px;
		text-align: left;
		vertical-align: top;
		cursor: text;
	}
	.empty:hover {
		border-color: var(--primary);
	}
	.md {
		min-height: 48px;
		padding: 10px 12px;
		border: 1px solid var(--line);
		border-radius: 10px;
		background: var(--surface);
		color: var(--ink);
		font-size: 15px;
		line-height: 1.55;
		cursor: text;
		overflow-wrap: anywhere;
	}
	.md:hover {
		border-color: var(--input);
	}
	.md :global(p),
	.md :global(ul),
	.md :global(ol),
	.md :global(blockquote) {
		margin: 0 0 8px;
	}
	.md :global(:last-child) {
		margin-bottom: 0;
	}
	.md :global(ul),
	.md :global(ol) {
		padding-left: 22px;
	}
	.md :global(ul) {
		list-style: disc;
	}
	.md :global(ol) {
		list-style: decimal;
	}
	.md :global(a) {
		text-decoration: underline;
	}
	.md :global(h4),
	.md :global(h5),
	.md :global(h6) {
		margin: 4px 0 6px;
		font-size: 15px;
	}
	.md :global(h4) {
		font-size: 17px;
	}
	.md :global(blockquote) {
		padding-left: 12px;
		border-left: 3px solid var(--line);
		color: var(--muted);
	}
	.md :global(code) {
		padding: 1px 5px;
		border-radius: 5px;
		background: var(--line-3);
		font-size: 0.9em;
	}
	.md :global(li.task) {
		list-style: none;
		margin-left: -20px;
	}
	.md :global(li.task .box) {
		display: inline-block;
		width: 12px;
		height: 12px;
		margin-right: 8px;
		border: 1.5px solid var(--input);
		border-radius: 3px;
		vertical-align: -1px;
	}
	.md :global(li.task.done) {
		color: var(--muted);
		text-decoration: line-through;
	}
	.md :global(li.task.done .box) {
		background: var(--primary);
		border-color: var(--primary);
	}
</style>
