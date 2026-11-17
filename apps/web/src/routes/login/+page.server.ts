import { redirect } from '@sveltejs/kit';
import { safeNext } from '#lib/api.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ parent, url }) => {
	const { shell } = await parent();
	if (shell.user) redirect(303, safeNext(url.searchParams.get('next')));
};
