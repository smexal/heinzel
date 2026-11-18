import { API_URL } from '$app/env/private';
import type { InboxPage } from './eingang/+page.server.ts';
import type { PageServerLoad } from './$types';

export type Widget = {
	key: string;
	module: string;
	eyebrow: string;
	title: string;
	link_label: string | null;
	link: string | null;
	items: { title: string; meta: string | null; tone: string | null; href: string | null }[];
	empty: string;
};

// Übersicht: open items of Mein Eingang and the widgets of active modules.
export const load: PageServerLoad = async ({ fetch }) => {
	const [inbox, home] = await Promise.all([
		fetch(`${API_URL}/api/v1/inbox?limit=4`),
		fetch(`${API_URL}/api/v1/home`)
	]);
	return {
		inbox: inbox.ok ? ((await inbox.json()) as InboxPage) : null,
		widgets: home.ok ? ((await home.json()).widgets as Widget[]) : []
	};
};
