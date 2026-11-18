import { error } from '@sveltejs/kit';
import { API_URL } from '$app/env/private';
import { apiQuery } from '#lib/audit.ts';
import type { PageServerLoad } from './$types';

export type AuditEvent = {
	id: number;
	at: string;
	actor_user_id: string | null;
	actor_name: string | null;
	channel: string;
	action: string;
	target_type: string | null;
	target_id: string | null;
	target_name: string | null;
	data: Record<string, unknown>;
	ip: string | null;
	hash: string;
	prev_hash: string;
};

export type AuditPage = {
	events: AuditEvent[];
	next_before_id: number | null;
	chain: { ok: boolean; events: number; checked_at: string; broken_at: number | null };
	actors: { id: string; name: string }[];
};

export const load: PageServerLoad = async ({ fetch, url }) => {
	const q = apiQuery(url.searchParams);
	const res = await fetch(`${API_URL}/api/v1/admin/audit?${q}`);
	if (res.status === 403) error(403, 'Keine Berechtigung');
	if (!res.ok) error(502, 'Audit-Log konnte nicht geladen werden');
	return { page: (await res.json()) as AuditPage, query: q.toString() };
};
