import { error } from '@sveltejs/kit';
import { API_URL } from '$app/env/private';
import type { PageServerLoad } from './$types';

export type InboxItem = {
	id: string;
	source: string;
	source_label: string;
	kind: 'task' | 'notice';
	severity: string | null;
	title: string;
	context: string | null;
	body: string | null;
	reason: string | null;
	facts: { label: string; value: string }[];
	link: string | null;
	actions: { key: string; label: string; style: string }[];
	attachments: {
		id: string;
		filename: string;
		content_type: string;
		size: number;
		url: string;
		is_image: boolean;
	}[];
	actor_name: string | null;
	due_at: string | null;
	created_at: string;
	updated_at: string;
	read: boolean;
	done: boolean;
};

export type InboxPage = {
	items: InboxItem[];
	counts: { open: number; tasks: number; notices: number; unread: number };
	sources: { key: string; label: string }[];
};

export const load: PageServerLoad = async ({ fetch, url }) => {
	const view = ['open', 'notices', 'done'].includes(url.searchParams.get('ansicht') ?? '')
		? url.searchParams.get('ansicht')!
		: 'open';
	const q = new URLSearchParams({ view });
	const source = url.searchParams.get('quelle');
	if (source) q.set('source', source);
	const res = await fetch(`${API_URL}/api/v1/inbox?${q}`);
	if (!res.ok) error(502, 'Mein Eingang konnte nicht geladen werden');
	return { inbox: (await res.json()) as InboxPage, view };
};
