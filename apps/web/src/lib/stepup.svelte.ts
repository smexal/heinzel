// Step-up confirmation for sensitive actions (role changes). The API answers
// 403 "step_up_required"; withStepUp() then asks for a fresh 2FA code (or the password
// without 2FA), confirms it and repeats the action once.

import { ApiError, post } from '#lib/api.ts';

type Pending = { resolve: (ok: boolean) => void };

export const stepUp = $state<{ open: boolean; pending: Pending | null }>({
	open: false,
	pending: null
});

function ask(): Promise<boolean> {
	return new Promise((resolve) => {
		stepUp.pending = { resolve };
		stepUp.open = true;
	});
}

/** Called by the dialog. Throws ApiError on a wrong code. */
export async function confirmStepUp(secret: { code?: string; password?: string }) {
	await post('/auth/step-up', secret);
	stepUp.open = false;
	stepUp.pending?.resolve(true);
	stepUp.pending = null;
}

export function cancelStepUp() {
	stepUp.open = false;
	stepUp.pending?.resolve(false);
	stepUp.pending = null;
}

export class StepUpCancelled extends Error {}

export async function withStepUp<T>(action: () => Promise<T>): Promise<T> {
	try {
		return await action();
	} catch (e) {
		if (!(e instanceof ApiError && e.detail === 'step_up_required')) throw e;
		if (!(await ask())) throw new StepUpCancelled('cancelled');
		return await action();
	}
}
