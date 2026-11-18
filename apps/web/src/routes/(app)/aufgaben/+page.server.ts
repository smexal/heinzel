import { error } from '@sveltejs/kit';
import { API_URL } from '$app/env/private';
import type { PageServerLoad } from './$types';

export type Person = { id: string; display_name: string; initials: string };

export type TaskList = {
	id: string;
	name: string;
	kind: 'personal' | 'shared';
	role: 'owner' | 'member';
	open: number;
	members: number;
};

export type Lists = {
	lists: TaskList[];
	can_share: boolean;
	assign_scope: 'list_members' | 'tenant';
	open: number;
	done: number;
};

export type Task = {
	id: string;
	list_id: string;
	list_name: string;
	list_kind: 'personal' | 'shared';
	title: string;
	note: string;
	due_date: string | null;
	due_label: string;
	due_tone: 'over' | 'today' | 'none' | '';
	status: 'open' | 'done';
	done_at: string | null;
	done_by: Person | null;
	assignee: Person | null;
	created_by: Person | null;
	created_at: string;
	images: number;
	can_delete: boolean;
};

export type TaskDetail = Task & {
	attachments: { id: string; filename: string; url: string; is_image: boolean }[];
	assignable: Person[];
};

export type Tasks = { tasks: Task[]; open: number; done: number };

const A = `${API_URL}/api/v1/aufgaben`;

export const load: PageServerLoad = async ({ fetch, url }) => {
	const list = url.searchParams.get('liste');
	const showDone = url.searchParams.get('erledigte') === '1';
	const taskId = url.searchParams.get('aufgabe');
	const q = new URLSearchParams();
	if (list) q.set('list', list);
	if (showDone) q.set('done', 'true');

	const [listsRes, tasksRes, detailRes] = await Promise.all([
		fetch(`${A}/lists`),
		fetch(`${A}/tasks?${q}`),
		taskId ? fetch(`${A}/tasks/${encodeURIComponent(taskId)}`) : Promise.resolve(null)
	]);
	if (listsRes.status === 404) error(404, 'Das Modul Aufgaben ist nicht aktiviert');
	if (listsRes.status === 403) error(403, 'Dafür fehlt dir die Berechtigung');
	if (!listsRes.ok) error(502, 'Aufgaben konnten nicht geladen werden');
	// An unknown or no longer visible list falls back to all lists.
	const tasks = tasksRes.ok
		? ((await tasksRes.json()) as Tasks)
		: ((await (await fetch(`${A}/tasks${showDone ? '?done=true' : ''}`)).json()) as Tasks);
	return {
		lists: (await listsRes.json()) as Lists,
		tasks,
		list: tasksRes.ok ? list : null,
		showDone,
		detail: detailRes?.ok ? ((await detailRes.json()) as TaskDetail) : null,
		detailMissing: !!taskId && !detailRes?.ok
	};
};
