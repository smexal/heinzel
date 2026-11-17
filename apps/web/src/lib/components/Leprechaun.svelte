<script lang="ts">
	// Heinzel product mark. Only for "powered by", never as tenant branding.
	let { size = 20 }: { size?: number } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
	<path d="M14 6h20l-2 16H16z" fill="#6B6F69" />
	<rect x="16.4" y="16.5" width="15.2" height="4.5" fill="#4A4F4A" />
	<rect
		x="21"
		y="16"
		width="6"
		height="5.5"
		rx="1"
		fill="none"
		stroke="#BDCF1F"
		stroke-width="1.8"
	/>
	<rect x="8" y="21" width="32" height="4" rx="2" fill="#6B6F69" />
	<circle cx="24" cy="31" r="7.5" fill="#D9D3C8" />
	<path
		d="M15.5 30.5c0 9 4 13 8.5 13s8.5-4 8.5-13c-2 4-5 5.5-8.5 5.5s-6.5-1.5-8.5-5.5z"
		fill="#A8A196"
	/>
</svg>
