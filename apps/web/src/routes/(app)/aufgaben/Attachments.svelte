<script lang="ts">
	// Attachments of a task: pictures as thumbnails, documents as lines; camera on phones.
	import { ApiError, post, send } from '#lib/api.ts';
	import { formatter } from '#lib/format.ts';
	import Icon from '#lib/components/Icon.svelte';
	import type { TaskDetail } from './+page.server.ts';

	let {
		task,
		busy,
		run,
		localization
	}: {
		task: TaskDetail;
		busy: boolean;
		run: (fn: () => Promise<unknown>, ok?: string) => Promise<void>;
		localization: Parameters<typeof formatter>[0];
	} = $props();

	const fmt = $derived(formatter(localization));
	// Browsers other than Safari cannot show HEIC: those appear as a file line.
	const SHOWN = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
	const pictures = $derived(task.attachments.filter((a) => SHOWN.includes(a.content_type)));
	const documents = $derived(task.attachments.filter((a) => !SHOWN.includes(a.content_type)));

	const ACCEPT = [
		'image/*',
		'.pdf',
		'.docx',
		'.xlsx',
		'.pptx',
		'.odt',
		'.ods',
		'.odp',
		'.txt',
		'.csv'
	].join(',');

	const KINDS: Record<string, string> = {
		'application/pdf': 'PDF',
		'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word',
		'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel',
		'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PowerPoint',
		'application/vnd.oasis.opendocument.text': 'Text (ODF)',
		'application/vnd.oasis.opendocument.spreadsheet': 'Tabelle (ODF)',
		'application/vnd.oasis.opendocument.presentation': 'Präsentation (ODF)',
		'text/plain': 'Text',
		'text/csv': 'CSV',
		'image/heic': 'Foto (HEIC)'
	};

	function size(bytes: number): string {
		if (bytes < 1024 * 1024) return `${fmt.number(Math.max(1, Math.round(bytes / 1024)), 0)} KB`;
		return `${fmt.number(bytes / 1024 / 1024, 1)} MB`;
	}

	async function upload(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		const chosen = Array.from(input.files ?? []);
		input.value = '';
		if (!chosen.length) return;
		const id = task.id;
		await run(
			async () => {
				const ids: string[] = [];
				for (const f of chosen) {
					const res = await fetch('/api/v1/files?module=aufgaben', {
						method: 'POST',
						headers: {
							'content-type': f.type || 'application/octet-stream',
							'x-filename': encodeURIComponent(f.name)
						},
						body: f,
						credentials: 'same-origin'
					});
					if (!res.ok) {
						const body = await res.json().catch(() => ({}));
						throw new ApiError(res.status, body.detail ?? `http_${res.status}`);
					}
					ids.push((await res.json()).id);
				}
				await post(`/aufgaben/tasks/${id}/attachments`, { attachment_ids: ids });
			},
			chosen.length > 1 ? `${chosen.length} Dateien angehängt.` : 'Datei angehängt.'
		);
	}

	const remove = (attId: string) =>
		run(() => send('DELETE', `/aufgaben/tasks/${task.id}/attachments/${attId}`));
</script>

<section class="att" aria-labelledby="att-h">
	<div class="head">
		<h3 id="att-h">Anhänge</h3>
		{#if task.attachments.length}<span class="sum">{task.attachments.length}</span>{/if}
	</div>

	{#if pictures.length}
		<div class="grid">
			{#each pictures as a (a.id)}
				<figure>
					<a href={a.url} target="_blank" rel="noopener" title={a.filename}>
						<img src={a.url} alt={a.filename} loading="lazy" />
					</a>
					<button
						type="button"
						class="rm"
						aria-label="Anhang entfernen: {a.filename}"
						disabled={busy}
						onclick={() => remove(a.id)}><Icon name="x" size={16} /></button
					>
				</figure>
			{/each}
		</div>
	{/if}

	{#if documents.length}
		<ul class="docs">
			{#each documents as a (a.id)}
				<li>
					<span class="ficon" aria-hidden="true"><Icon name="file" size={20} /></span>
					<a class="fname" href="{a.url}?download=true" download={a.filename}>
						<span class="n">{a.filename}</span>
						<span class="m">{KINDS[a.content_type] ?? 'Datei'} · {size(a.size)}</span>
					</a>
					<button
						type="button"
						class="x"
						aria-label="Anhang entfernen: {a.filename}"
						disabled={busy}
						onclick={() => remove(a.id)}><Icon name="x" size={16} /></button
					>
				</li>
			{/each}
		</ul>
	{/if}

	<div class="adds">
		<label class="add camera">
			<Icon name="camera" size={18} />
			<span>Foto aufnehmen</span>
			<input
				class="sr-only"
				type="file"
				accept="image/*"
				capture="environment"
				disabled={busy}
				onchange={upload}
			/>
		</label>
		<label class="add">
			<Icon name="paperclip" size={18} />
			<span>Datei hinzufügen</span>
			<input
				class="sr-only"
				type="file"
				accept={ACCEPT}
				multiple
				disabled={busy}
				onchange={upload}
			/>
		</label>
	</div>
	<small
		>Bilder, PDF, Word, Excel, PowerPoint, OpenDocument, TXT und CSV, bis 15 MB pro Datei.</small
	>
</section>

<style>
	.att {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.head {
		display: flex;
		align-items: baseline;
		gap: 8px;
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
	.grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 10px;
	}
	figure {
		position: relative;
		overflow: hidden;
		aspect-ratio: 1;
		margin: 0;
		border-radius: 10px;
		background: var(--line-3);
	}
	figure img {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.rm {
		position: absolute;
		top: 4px;
		right: 4px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		height: 30px;
		border: 0;
		border-radius: 50%;
		background: rgb(0 0 0 / 0.55);
		color: #fff;
		cursor: pointer;
	}
	.docs {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.docs li {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 6px 8px 10px;
		border: 1px solid var(--line);
		border-radius: 10px;
		background: var(--surface);
	}
	.ficon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: 36px;
		height: 36px;
		border-radius: 8px;
		background: var(--info-bg);
		color: var(--info-ink);
	}
	.fname {
		display: flex;
		flex: 1;
		flex-direction: column;
		min-width: 0;
		color: var(--ink);
		text-decoration: none;
	}
	.fname:hover .n {
		text-decoration: underline;
	}
	.n {
		overflow: hidden;
		font-size: 14px;
		font-weight: 600;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.m {
		color: var(--muted);
		font-size: 12px;
	}
	.x {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: 36px;
		height: 36px;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: var(--muted);
		cursor: pointer;
	}
	.x:hover {
		background: var(--line-2);
		color: var(--ink);
	}
	.adds {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.add {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		min-height: 44px;
		padding: 0 14px;
		border: 1.5px dashed color-mix(in oklab, var(--primary) 40%, var(--surface));
		border-radius: 10px;
		background: color-mix(in oklab, var(--primary) 7%, var(--surface));
		color: var(--primary-strong);
		font-size: 14px;
		font-weight: 600;
		cursor: pointer;
	}
	.add:focus-within,
	.x:focus-visible,
	.rm:focus-visible {
		outline: 2px solid var(--primary);
		outline-offset: 2px;
	}
	/* The camera button only where there is a camera to open (phones and tablets). */
	@media (hover: hover) and (pointer: fine) {
		.camera {
			display: none;
		}
	}
	small {
		color: var(--muted);
		font-size: 12px;
	}
</style>
