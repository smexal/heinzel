import { redirect } from '@sveltejs/kit';
import type { LayoutServerLoad } from './$types';

// Everything in (app) needs a signed-in user.
export const load: LayoutServerLoad = async ({ parent, url }) => {
	const { shell } = await parent();
	if (!shell.user) {
		redirect(303, `/login?next=${encodeURIComponent(url.pathname + url.search)}`);
	}
};
