import type { LyricsMode } from "./types"

export const LYRICS_MAX_LENGTH = 5000

export const SECTION_TEMPLATE = "[VERSE 1]\n\n[PRE-HOOK]\n\n[HOOK]\n\n[VERSE 2]\n\n[BRIDGE]\n\n[OUTRO]\n"

/**
 * Resolve the lyrics payload for a generation request from the explorer stage.
 * "ai" (surprise me) → null (backend writes lyrics); otherwise the trimmed
 * editor text, or null when the editor is blank so the backend treats it
 * the same as AI-written lyrics instead of 422ing on blank input.
 */
export function resolveApprovedLyrics(mode: LyricsMode, lyricsText: string): string | null {
	if (mode === "ai") return null
	const trimmed = lyricsText.trim()
	return trimmed.length > 0 ? trimmed : null
}
