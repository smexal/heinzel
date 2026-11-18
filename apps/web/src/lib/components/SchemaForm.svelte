<script lang="ts">
	// Form for module settings from a JSON Schema (draft 2020-12, the subset modules use):
	// enums → select (labels from "x-enum-labels"), booleans → switches, strings, integers.
	// Booleans with "x-group" are listed under that heading.

	type Prop = {
		type?: string | string[];
		enum?: unknown[];
		title?: string;
		description?: string;
		minLength?: number;
		maxLength?: number;
		minimum?: number;
		maximum?: number;
		'x-enum-labels'?: Record<string, string>;
		'x-group'?: string;
	};

	let {
		schema,
		values = $bindable(),
		idPrefix = 'set'
	}: {
		schema: { properties?: Record<string, unknown> };
		values: Record<string, unknown>;
		idPrefix?: string;
	} = $props();

	const entries = $derived(Object.entries((schema.properties ?? {}) as Record<string, Prop>));
	const fields = $derived(entries.filter(([, p]) => !isBool(p)));
	const switches = $derived(entries.filter(([, p]) => isBool(p) && !p['x-group']));
	const groups = $derived(
		Object.entries(
			entries
				.filter(([, p]) => isBool(p) && p['x-group'])
				.reduce<Record<string, [string, Prop][]>>((acc, e) => {
					(acc[e[1]['x-group'] as string] ??= []).push(e);
					return acc;
				}, {})
		)
	);

	function isBool(p: Prop) {
		return p.type === 'boolean';
	}
	function types(p: Prop): string[] {
		return Array.isArray(p.type) ? p.type : p.type ? [p.type] : [];
	}
	const label = (p: Prop, v: unknown) => p['x-enum-labels']?.[String(v)] ?? String(v ?? '—');
</script>

{#if fields.length}
	<div class="grid">
		{#each fields as [key, p] (key)}
			<div class="f">
				<label for="{idPrefix}-{key}">{p.title ?? key}</label>
				{#if p.enum}
					<select
						id="{idPrefix}-{key}"
						class="input"
						value={JSON.stringify(values[key] ?? null)}
						onchange={(e) => (values[key] = JSON.parse(e.currentTarget.value))}
					>
						{#each p.enum as v (JSON.stringify(v))}
							<option value={JSON.stringify(v)}>{label(p, v)}</option>
						{/each}
					</select>
				{:else if types(p).includes('integer') || types(p).includes('number')}
					<input
						id="{idPrefix}-{key}"
						class="input"
						type="number"
						min={p.minimum}
						max={p.maximum}
						value={values[key] as number}
						oninput={(e) => (values[key] = e.currentTarget.valueAsNumber)}
					/>
				{:else}
					<input
						id="{idPrefix}-{key}"
						class="input"
						minlength={p.minLength}
						maxlength={p.maxLength}
						value={(values[key] as string) ?? ''}
						oninput={(e) => (values[key] = e.currentTarget.value)}
					/>
				{/if}
				{#if p.description}<small>{p.description}</small>{/if}
			</div>
		{/each}
	</div>
{/if}

{#each [[null, switches] as const, ...groups.map(([g, list]) => [g, list] as const)] as [group, list], i (group ?? i)}
	{#if list.length}
		{#if group}<h4>{group}</h4>{/if}
		<div class="rows">
			{#each list as [key, p] (key)}
				<label class="row">
					<span
						>{p.title ?? key}{#if p.description}<small>{p.description}</small>{/if}</span
					>
					<input
						type="checkbox"
						role="switch"
						checked={Boolean(values[key])}
						onchange={(e) => (values[key] = e.currentTarget.checked)}
					/>
				</label>
			{/each}
		</div>
	{/if}
{/each}

<style>
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
		gap: 18px;
	}
	.f {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.f label {
		font-size: 14px;
		font-weight: 600;
	}
	small {
		display: block;
		font-size: 13px;
		color: var(--muted);
		font-weight: 400;
	}
	h4 {
		margin: 18px 0 0;
		font-size: 15px;
	}
	.rows {
		display: flex;
		flex-direction: column;
		margin-top: 6px;
	}
	.row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		min-height: 48px;
		border-bottom: 1px solid var(--line-3);
		font-size: 15px;
		font-weight: 600;
		cursor: pointer;
	}
	.row:last-child {
		border-bottom: 0;
	}
	.row input {
		width: 18px;
		height: 18px;
		accent-color: var(--primary);
	}
</style>
