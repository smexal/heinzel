import { API_URL } from '$app/env/private';
import type { InboxPage } from './eingang/+page.server.ts';
import type { PageServerLoad } from './$types';

// Übersicht: the open items of Mein Eingang at a glance.
export const load: PageServerLoad = async ({ fetch }) => {
	const res = await fetch(`${API_URL}/api/v1/inbox?limit=4`);
	return { inbox: res.ok ? ((await res.json()) as InboxPage) : null };
};
