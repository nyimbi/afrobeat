import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs))
}

export function formatDuration(seconds: number): string {
	const m = Math.floor(seconds / 60)
	const s = Math.floor(seconds % 60)
	return `${m}:${s.toString().padStart(2, "0")}`
}

export function formatPlayCount(count: number): string {
	if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`
	if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`
	return count.toString()
}

export function formatRelativeDate(iso: string): string {
	const diff = Date.now() - new Date(iso).getTime()
	const mins = Math.floor(diff / 60_000)
	const hours = Math.floor(diff / 3_600_000)
	const days = Math.floor(diff / 86_400_000)
	if (mins < 1) return "just now"
	if (mins < 60) return `${mins}m ago`
	if (hours < 24) return `${hours}h ago`
	if (days < 7) return `${days}d ago`
	return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

export function subGenreLabel(sg: string): string {
	const map: Record<string, string> = {
		afropop: "Afropop",
		afrofusion: "Afrofusion",
		alte: "Alte",
		amapiano_cross: "Amapiano",
		uk_afrobeats: "UK Afrobeats",
		afrobeats: "Afrobeats",
		highlife: "Highlife",
		bongo_flava: "Bongo Flava",
		soukous: "Soukous",
		mbalax: "Mbalax",
		soca: "Soca",
		calypso: "Calypso",
		gengetone: "Gengetone",
		benga: "Benga",
		taarab: "Taarab",
		afro_soca: "Afro-Soca",
	}
	return map[sg] ?? sg
}

export function languageFlag(lang: string): string {
	const map: Record<string, string> = {
		english: "🇬🇧",
		pidgin: "🇳🇬",
		yoruba: "🟡",
		igbo: "🟢",
		mix: "🌍",
		swahili: "🇹🇿",
		lingala: "🇨🇩",
		zulu: "🇿🇦",
		twi: "🇬🇭",
	}
	return map[lang] ?? "🌍"
}
