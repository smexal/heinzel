<script lang="ts">
	// Checklist of a task: tick, rename in place, reorder (drag or Alt+↑/↓), remove, add.
	import { untrack } from 'svelte';
	import { post, send } from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';
	import type { CheckItem, TaskDetail } from './+page.server.ts';

	let {
		task,
		busy,
		run,
		onfinish
	}: {
		task: TaskDetail;
		busy: boolean;
		run: (fn: () => Promise<unknown>, ok?: string) => Promise<void>;
		onfinish: () => void;
	} = $props();

	const items = $derived(task.checklist);
	const total = $derived(items.length);
	const done = $derived(items.filter((i) => i.done).length);
	const pct = $derived(total ? Math.round((done / total) * 100) : 0);

	// Editable copies of the texts, re-taken when the task's checklist changes.
	let texts = $state<Record<string, string>>({});
	$effect(() => {
		const list = items;
		untrack(() => (texts = Object.fromEntries(list.map((i) => [i.id, i.text]))));
	});

	const base = $derived(`/aufgaben/tasks/${task.id}/checklist`);
	const patch = (item: CheckItem, body: Record<string, unknown>) =>
		run(() => send('PATCH', `${base}/${item.id}`, body));

	async function tick(item: CheckItem, done: boolean) {
		saving = item.id;
		await patch(item, { done });
		saving = null;
	}

	function saveText(item: CheckItem) {
		const t = (texts[item.id] ?? '').trim();
		if (!t) texts[item.id] = item.text;
		else if (t !== item.text) patch(item, { text: t });
	}

	async function move(item: CheckItem, to: number, focusAfter = false) {
		if (to < 0 || to >= items.length) return;
		await patch(item, { position: to });
		if (focusAfter) document.getElementById(`ck-t-${item.id}`)?.focus();
	}

	function keys(e: KeyboardEvent, item: CheckItem, index: number) {
		if (e.key === 'Enter') {
			e.preventDefault();
			(e.currentTarget as HTMLInputElement).blur();
		} else if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
			e.preventDefault();
			saveText(item);
			move(item, index + (e.key === 'ArrowUp' ? -1 : 1), true);
		}
	}

	// Drag and drop by the handle
	let dragId = $state<string | null>(null);
	let overIndex = $state<number | null>(null);
	function drop(index: number) {
		const item = items.find((i) => i.id === dragId);
		dragId = null;
		overIndex = null;
		if (item && items.indexOf(item) !== index) move(item, index);
	}

	let newText = $state('');
	let adding = $state(false);
	// The point whose checkbox is being saved
	let saving = $state<string | null>(null);
	let addInput = $state<HTMLInputElement>();
	async function add(e: SubmitEvent) {
		e.preventDefault();
		const text = newText.trim();
		if (!text) return;
		newText = '';
		adding = true;
		await run(() => post(base, { text }));
		adding = false;
		addInput?.focus();
	}
</script>

<section class="ck" aria-labelledby="ck-h">
	<div class="head">
		<h3 id="ck-h">Checkliste</h3>
		{#if total}<span class="sum">{done} von {total} erledigt</span>{/if}
	</div>
	{#if total}
		<div
			class="bar"
			role="progressbar"
			aria-label="Fortschritt der Checkliste"
			aria-valuemin="0"
			aria-valuemax={total}
			aria-valuenow={done}
		>
			<span class:full={done === total} style="width: {pct}%"></span>
		</div>
		<ul>
			{#each items as item, index (item.id)}
				<li
					class:dragging={dragId === item.id}
					class:over={overIndex === index && dragId !== item.id}
					ondragover={(e) => {
						if (!dragId) return;
						e.preventDefault();
						overIndex = index;
					}}
					ondrop={(e) => {
						e.preventDefault();
						drop(index);
					}}
				>
					<span
						class="grip"
						draggable="true"
						role="presentation"
						title="Ziehen zum Verschieben (oder Alt+↑/↓)"
						ondragstart={(e) => {
							dragId = item.id;
							e.dataTransfer?.setData('text/plain', item.id);
						}}
						ondragend={() => {
							dragId = null;
							overIndex = null;
						}}><Icon name="grip" size={14} /></span
					>
					{#if saving === item.id}
						<span class="cb-spin" role="status" aria-label="Wird gespeichert"
							><span class="spinner"></span></span
						>
					{:else}
						<input
							class="cb"
							type="checkbox"
							checked={item.done}
							disabled={busy}
							aria-label="{item.done ? 'Nicht erledigt' : 'Erledigt'}: {item.text}"
							onchange={(e) => tick(item, e.currentTarget.checked)}
						/>
					{/if}
					<label class="sr-only" for="ck-t-{item.id}">Punkt {index + 1}</label>
					<input
						id="ck-t-{item.id}"
						class="txt"
						class:done={item.done}
						maxlength="200"
						bind:value={texts[item.id]}
						onblur={() => saveText(item)}
						onkeydown={(e) => keys(e, item, index)}
					/>
					<button
						type="button"
						class="x"
						aria-label="Punkt entfernen: {item.text}"
						disabled={busy}
						onclick={() => run(() => send('DELETE', `${base}/${item.id}`))}
						><Icon name="x" size={16} /></button
					>
				</li>
			{/each}
		</ul>
	{/if}
	<form class="add" onsubmit={add}>
		{#if adding}<span class="spinner" role="status" aria-label="Wird gespeichert"
			></span>{:else}<Icon name="plus" size={18} />{/if}
		<label class="sr-only" for="ck-new">Neuer Punkt</label>
		<input
			id="ck-new"
			bind:this={addInput}
			bind:value={newText}
			maxlength="200"
			autocomplete="off"
			placeholder="Punkt hinzufügen und Enter drücken"
		/>
	</form>
	{#if total && done === total && task.status === 'open'}
		<div class="finish" role="status">
			<span>Alle Punkte erledigt.</span>
			<button class="btn btn-secondary small" type="button" disabled={busy} onclick={onfinish}
				>Aufgabe abschliessen</button
			>
		</div>
	{/if}
</section>

<style>
	.ck {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 12px;
	}
	h3 {
		margin: 0;
		color: var(--ink-2);
		font-size: 14px;
		font-weight: 600;
	}
	.sum {
		color: var(--muted);
		font-size: 13px;
	}
	.bar {
		height: 6px;
		overflow: hidden;
		border-radius: 999px;
		background: var(--line-3);
	}
	.bar span {
		display: block;
		height: 100%;
		border-radius: 999px;
		background: var(--primary);
		transition: width 0.2s;
	}
	.bar span.full {
		background: var(--ok-ink);
	}
	ul {
		display: flex;
		flex-direction: column;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	li {
		display: flex;
		align-items: center;
		gap: 8px;
		min-height: 44px;
		padding: 0 4px;
		border-radius: 8px;
		border-top: 2px solid transparent;
	}
	li:hover {
		background: var(--hover);
	}
	li.dragging {
		opacity: 0.5;
	}
	li.over {
		border-top-color: var(--primary);
	}
	.grip {
		display: inline-flex;
		color: var(--muted);
		cursor: grab;
	}
	.cb {
		appearance: none;
		display: grid;
		place-content: center;
		flex: none;
		width: 20px;
		height: 20px;
		margin: 0;
		border: 2px solid var(--input);
		border-radius: 6px;
		background: var(--surface);
		cursor: pointer;
	}
	.cb-spin {
		display: grid;
		place-content: center;
		flex: none;
		width: 20px;
		height: 20px;
		color: var(--primary);
	}
	.cb:checked {
		background: var(--primary);
		border-color: var(--primary);
	}
	.cb:checked::after {
		content: '';
		width: 5px;
		height: 10px;
		border: solid #fff;
		border-width: 0 2.5px 2.5px 0;
		transform: rotate(45deg) translate(-1px, -1px);
	}
	.cb:focus-visible,
	.x:focus-visible {
		outline: 2px solid var(--primary);
		outline-offset: 2px;
	}
	.txt {
		flex: 1;
		min-width: 0;
		min-height: 36px;
		padding: 0 6px;
		border: 1px solid transparent;
		border-radius: 6px;
		background: transparent;
		color: var(--ink);
		font: inherit;
		font-size: 15px;
	}
	.txt.done {
		color: var(--muted);
		text-decoration: line-through;
	}
	.txt:focus {
		outline: none;
		border-color: var(--primary);
		background: var(--surface);
		text-decoration: none;
	}
	.x {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: var(--muted);
		cursor: pointer;
		opacity: 0;
	}
	li:hover .x,
	li:focus-within .x {
		opacity: 1;
	}
	.x:hover {
		background: var(--line-2);
		color: var(--ink);
	}
	@media (hover: none) {
		.x {
			opacity: 1;
		}
	}
	.add {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 0 8px 0 10px;
		border: 1px dashed var(--input);
		border-radius: 10px;
		color: var(--primary);
	}
	.add:focus-within {
		border-style: solid;
		border-color: var(--primary);
	}
	.add input {
		flex: 1;
		min-width: 0;
		min-height: 40px;
		border: 0;
		outline: none;
		background: transparent;
		color: var(--ink);
		font: inherit;
		font-size: 15px;
	}
	.finish {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		padding: 10px 12px;
		border-radius: 10px;
		background: var(--ok-bg);
		color: var(--ok-ink);
		font-size: 14px;
		font-weight: 600;
	}
	.small {
		min-height: 36px;
		padding: 0 12px;
		font-size: 14px;
	}
</style>
