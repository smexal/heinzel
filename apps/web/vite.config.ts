import tailwindcss from '@tailwindcss/vite';
import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const apiUrl = process.env.API_URL ?? 'http://localhost:8000';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			adapter: adapter()
		})
	],
	server: {
		// Browser requests to /api go to the FastAPI core in dev. Keep the Host header: the API
		// resolves the tenant from it and checks it against the Origin of write requests.
		// In production the reverse proxy does the same (proxy_set_header Host $host).
		proxy: { '/api': { target: apiUrl, changeOrigin: false, xfwd: true } }
	}
});
