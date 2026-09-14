"use client"

import { useCallback, useState } from "react"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"
import { LYRICS_MAX_LENGTH, SECTION_TEMPLATE } from "@/lib/lyrics"
import type { LyricDraft, LyricsMode } from "@/lib/types"

interface LyricsStageProps {
	prompt: string
	subGenre: string
	language: string
	disabled?: boolean
	mode: LyricsMode
	onModeChange: (mode: LyricsMode) => void
	lyricsText: string
	onLyricsTextChange: (text: string) => void
}

function SectionLabel({ children }: { children: React.ReactNode }) {
	return (
		<span className="text-[10px] font-mono uppercase tracking-widest text-zinc-600">
			{children}
		</span>
	)
}

export function LyricsStage({
	prompt,
	subGenre,
	language,
	disabled = false,
	mode,
	onModeChange,
	lyricsText,
	onLyricsTextChange,
}: LyricsStageProps) {
	const [lyricTheme, setLyricTheme] = useState("")
	const [lyricDrafts, setLyricDrafts] = useState<LyricDraft[]>([])
	const [activeDraft, setActiveDraft] = useState(0)
	const [isDrafting, setIsDrafting] = useState(false)
	const [draftError, setDraftError] = useState<string | null>(null)

	const busy = disabled || isDrafting
	const useCustomLyrics = lyricsText.trim().length > 0
	const activeDraftMeta = lyricDrafts[activeDraft] ?? null

	const handleDraftLyrics = useCallback(async () => {
		const theme = lyricTheme.trim() || prompt.trim()
		if (!theme || isDrafting) return
		setIsDrafting(true)
		setDraftError(null)
		try {
			const draft = await api.lyrics.draftLyrics({ prompt: theme, subGenre, language })
			setLyricDrafts((prev) => {
				setActiveDraft(prev.length)
				return [...prev, draft]
			})
			onLyricsTextChange(draft.fullLyrics)
		} catch (err: unknown) {
			setDraftError(err instanceof Error ? err.message : "Lyric draft failed")
		} finally {
			setIsDrafting(false)
		}
	}, [lyricTheme, prompt, subGenre, language, isDrafting, onLyricsTextChange])

	const handleSelectDraft = useCallback(
		(i: number) => {
			const d = lyricDrafts[i]
			if (!d) return
			setActiveDraft(i)
			onLyricsTextChange(d.fullLyrics)
			setDraftError(null)
		},
		[lyricDrafts, onLyricsTextChange],
	)

	const handleInsertTemplate = useCallback(() => {
		if (lyricsText.trim().length === 0) {
			onLyricsTextChange(SECTION_TEMPLATE)
		}
	}, [lyricsText, onLyricsTextChange])

	return (
		<div className="space-y-2">
			<SectionLabel>Lyrics</SectionLabel>
			<div className="grid grid-cols-3 gap-1.5">
				{(
					[
						{ id: "describe", label: "Describe" },
						{ id: "write", label: "Write" },
						{ id: "ai", label: "Surprise me" },
					] as const
				).map((m) => (
					<button
						key={m.id}
						onClick={() => onModeChange(m.id)}
						disabled={disabled}
						className={cn(
							"py-2 rounded-lg text-xs font-medium border transition-all",
							mode === m.id
								? "border-afro-gold/50 bg-afro-gold/10 text-afro-gold"
								: "border-white/[0.07] text-zinc-500 hover:border-white/[0.14] hover:text-zinc-300",
							"disabled:opacity-50",
						)}
					>
						{m.label}
						{useCustomLyrics && mode === m.id && m.id !== "ai" ? " ✓" : ""}
					</button>
				))}
			</div>

			{mode === "ai" && (
				<p className="text-[10px] text-zinc-700">
					Gbẹdu writes lyrics during generation — nothing to do here.
				</p>
			)}

			{mode === "describe" && (
				<div className="space-y-2 animate-slide-up">
					<input
						value={lyricTheme}
						onChange={(e) => setLyricTheme(e.target.value)}
						disabled={busy}
						placeholder="Theme — defaults to your vibe above"
						aria-label="Lyric theme"
						className="w-full px-3 py-2 rounded-lg bg-dark-bg-elevated border border-white/[0.08] text-sm text-zinc-100 placeholder:text-zinc-700 focus:outline-none focus:ring-1 focus:ring-afro-gold/50 disabled:opacity-50"
					/>
					<button
						onClick={() => void handleDraftLyrics()}
						disabled={busy || !(lyricTheme.trim() || prompt.trim())}
						className="w-full py-2.5 rounded-lg text-xs font-semibold border border-afro-gold/40 bg-afro-gold/10 text-afro-gold hover:bg-afro-gold/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
					>
						{isDrafting
							? "Drafting lyrics..."
							: lyricDrafts.length > 0
								? "Regenerate draft (free)"
								: "Draft lyrics (free preview)"}
					</button>
					{draftError && (
						<p role="alert" className="text-[10px] text-red-400">
							{draftError}
						</p>
					)}
					{lyricDrafts.length > 1 && (
						<div className="flex flex-wrap gap-1.5">
							{lyricDrafts.map((_, i) => (
								<button
									key={i}
									onClick={() => handleSelectDraft(i)}
									disabled={busy}
									className={cn(
										"px-2.5 py-1 rounded-full text-[10px] font-mono border transition-all",
										i === activeDraft
											? "border-afro-gold/50 bg-afro-gold/10 text-afro-gold"
											: "border-white/[0.07] text-zinc-600 hover:text-zinc-400",
									)}
								>
									Draft {i + 1}
								</button>
							))}
						</div>
					)}
					{lyricDrafts.length > 0 && (
						<div className="space-y-1.5">
							<textarea
								value={lyricsText}
								onChange={(e) => onLyricsTextChange(e.target.value.slice(0, LYRICS_MAX_LENGTH))}
								disabled={busy}
								rows={8}
								aria-label="Lyric draft editor"
								className="w-full px-3 py-2 rounded-lg bg-dark-bg-elevated border border-white/[0.08] text-sm text-zinc-100 placeholder:text-zinc-700 focus:outline-none focus:ring-1 focus:ring-afro-gold/50 disabled:opacity-50 resize-y min-h-32 font-mono leading-relaxed"
							/>
							<div className="flex items-center justify-between">
								<p className="text-[10px] text-zinc-700">
									{activeDraftMeta?.fellBackToEnglish && activeDraftMeta.languageDisclosure
										? activeDraftMeta.languageDisclosure
										: `Draft ${activeDraft + 1} · edit freely — these exact words will be used.`}
								</p>
								<span className="font-mono text-[10px] text-zinc-700 tabular-nums">
									{lyricsText.length}/{LYRICS_MAX_LENGTH}
								</span>
							</div>
						</div>
					)}
				</div>
			)}

			{mode === "write" && (
				<div className="space-y-1.5 animate-slide-up">
					<textarea
						value={lyricsText}
						onChange={(e) => onLyricsTextChange(e.target.value.slice(0, LYRICS_MAX_LENGTH))}
						disabled={disabled}
						rows={8}
						placeholder={"Paste or write your lyrics here..."}
						aria-label="Lyrics editor"
						className="w-full px-3 py-2 rounded-lg bg-dark-bg-elevated border border-white/[0.08] text-sm text-zinc-100 placeholder:text-zinc-700 focus:outline-none focus:ring-1 focus:ring-afro-gold/50 disabled:opacity-50 resize-y min-h-32 font-mono leading-relaxed"
					/>
					<div className="flex items-center justify-between">
						<button
							onClick={handleInsertTemplate}
							disabled={disabled || lyricsText.trim().length > 0}
							className="text-[10px] text-zinc-600 hover:text-afro-gold transition-colors disabled:opacity-40"
						>
							Insert section template
						</button>
						<span className="font-mono text-[10px] text-zinc-700 tabular-nums">
							{lyricsText.length}/{LYRICS_MAX_LENGTH}
						</span>
					</div>
				</div>
			)}
		</div>
	)
}
