"use client"

import { useState, useCallback } from "react"
import * as Slider from "@radix-ui/react-slider"
import * as Tooltip from "@radix-ui/react-tooltip"
import {
	Sparkles,
	Download,
	Share2,
	BookmarkPlus,
	RefreshCw,
	Music2,
	ChevronDown,
	ChevronUp,
	AlertCircle,
	Copy,
	Check,
} from "lucide-react"
import { useGenerationStore } from "@/store/generation"
import { useAuthStore } from "@/store/auth"
import { PromptInput } from "@/components/studio/prompt-input"
import { GenerationProgress } from "@/components/ui/generation-progress"
import { AudioPlayer } from "@/components/ui/audio-player"
import { UpgradeModal } from "@/components/payments/upgrade-modal"
import { Navbar } from "@/components/layout/navbar"
import { cn, subGenreLabel, languageFlag, formatDuration } from "@/lib/utils"
import { api } from "@/lib/api"
import type { SubGenre, Language } from "@/lib/types"

// ---- Static options ----

const SUB_GENRES: { id: SubGenre; label: string; emoji: string }[] = [
	{ id: "afropop", label: "Afropop", emoji: "🌟" },
	{ id: "afrofusion", label: "Afrofusion", emoji: "🔥" },
	{ id: "alte", label: "Alte", emoji: "🎸" },
	{ id: "amapiano", label: "Amapiano", emoji: "🪗" },
	{ id: "uk_afrobeats", label: "UK Afrobeats", emoji: "👑" },
]

const LANGUAGES: { id: Language; label: string; flag: string }[] = [
	{ id: "english", label: "English", flag: "🇬🇧" },
	{ id: "pidgin", label: "Pidgin", flag: "🇳🇬" },
	{ id: "yoruba", label: "Yoruba", flag: "🟡" },
	{ id: "igbo", label: "Igbo", flag: "🟢" },
	{ id: "mix", label: "Mix", flag: "🌍" },
]

const DURATIONS: { value: 30 | 60 | 120 | 210; label: string }[] = [
	{ value: 30, label: "30s" },
	{ value: 60, label: "1 min" },
	{ value: 120, label: "2 min" },
	{ value: 210, label: "Full" },
]

const ENERGY_EMOJIS = ["😴", "😌", "🙂", "😊", "😎", "🙌", "💃", "🔥", "⚡", "🚀"]

const GENRE_BADGE_COLORS: Record<SubGenre, string> = {
	afropop: "bg-amber-500/15 text-amber-400 border-amber-500/25",
	afrofusion: "bg-orange-500/15 text-orange-400 border-orange-500/25",
	alte: "bg-purple-500/15 text-purple-400 border-purple-500/25",
	amapiano: "bg-green-500/15 text-green-400 border-green-500/25",
	uk_afrobeats: "bg-blue-500/15 text-blue-400 border-blue-500/25",
}

// ---- Sub-components ----

function SectionLabel({ children }: { children: React.ReactNode }) {
	return (
		<span className="text-[10px] font-mono uppercase tracking-widest text-zinc-600">
			{children}
		</span>
	)
}

// ---- Main page ----

export default function StudioPage() {
	const { user } = useAuthStore()
	const {
		isGenerating,
		jobStatus,
		progressPercent,
		statusMessage,
		currentTrack,
		error,
		submitGeneration,
		cancelGeneration,
		reset,
	} = useGenerationStore()

	// Form state
	const [prompt, setPrompt] = useState("")
	const [subGenre, setSubGenre] = useState<SubGenre>("afropop")
	const [language, setLanguage] = useState<Language>("english")
	const [energy, setEnergy] = useState(6)
	const [duration, setDuration] = useState<30 | 60 | 120 | 210>(60)
	const [showAdvanced, setShowAdvanced] = useState(false)
	const [bpmOverride, setBpmOverride] = useState<string>("")
	const [voiceModelId] = useState<string | null>(null)

	// UI state
	const [showUpgrade, setShowUpgrade] = useState(false)
	const [copied, setCopied] = useState(false)
	const [isDownloading, setIsDownloading] = useState(false)

	const canDownload = user?.subscriptionTier !== "free"
	const canGetStems = user?.subscriptionTier === "pro" || user?.subscriptionTier === "label"

	const handleGenerate = useCallback(async () => {
		if (!prompt.trim()) return
		await submitGeneration({
			prompt: prompt.trim(),
			subGenre,
			language,
			energyLevel: energy,
			durationSeconds: duration,
			bpmOverride: bpmOverride ? parseInt(bpmOverride, 10) : null,
			voiceModelId,
		})
	}, [prompt, subGenre, language, energy, duration, bpmOverride, voiceModelId, submitGeneration])

	const handleDownload = useCallback(async () => {
		if (!currentTrack) return
		if (!canDownload) {
			setShowUpgrade(true)
			return
		}
		setIsDownloading(true)
		try {
			const { url } = await api.tracks.getDownloadUrl(currentTrack.id, "mp3")
			const a = document.createElement("a")
			a.href = url
			a.download = `${currentTrack.title}.mp3`
			a.click()
		} catch {
			// silently fail — user sees nothing odd
		} finally {
			setIsDownloading(false)
		}
	}, [currentTrack, canDownload])

	const handleShare = useCallback(async () => {
		if (!currentTrack) return
		const url = `${window.location.origin}/track/${currentTrack.id}`
		await navigator.clipboard.writeText(url)
		setCopied(true)
		setTimeout(() => setCopied(false), 2_500)
	}, [currentTrack])

	const handleGetStems = useCallback(() => {
		if (!canGetStems) {
			setShowUpgrade(true)
		}
	}, [canGetStems])

	const showProgress = isGenerating && !currentTrack
	const showPlayer = currentTrack?.audioUrl || currentTrack?.previewUrl

	return (
		<Tooltip.Provider delayDuration={400}>
			<div className="min-h-dvh bg-dark-bg-primary flex flex-col">
				<Navbar />

				{/* Main grid */}
				<main className="flex-1 flex flex-col lg:flex-row pt-16 overflow-hidden">
					{/* ===== LEFT PANEL — Generation controls ===== */}
					<aside className="w-full lg:w-[42%] xl:w-[38%] flex flex-col border-b lg:border-b-0 lg:border-r border-white/[0.06] overflow-y-auto">
						<div className="flex-1 p-5 sm:p-6 space-y-6">
							{/* Header */}
							<div className="space-y-0.5">
								<h1 className="font-display text-2xl font-bold text-zinc-100 leading-tight">
									Make Your Track
								</h1>
								<p className="text-xs text-zinc-600">
									Describe your vibe — Gbẹdu does the rest
								</p>
							</div>

							{/* Prompt */}
							<div className="space-y-2">
								<SectionLabel>Your vibe</SectionLabel>
								<PromptInput
									value={prompt}
									onChange={setPrompt}
									disabled={isGenerating}
								/>
							</div>

							{/* Sub-genre */}
							<div className="space-y-2">
								<SectionLabel>Sub-genre</SectionLabel>
								<div className="flex flex-wrap gap-2">
									{SUB_GENRES.map((g) => (
										<button
											key={g.id}
											onClick={() => setSubGenre(g.id)}
											disabled={isGenerating}
											className={cn(
												"flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-all",
												subGenre === g.id
													? cn(GENRE_BADGE_COLORS[g.id], "shadow-sm")
													: "border-white/[0.07] text-zinc-500 hover:border-white/[0.14] hover:text-zinc-300",
												"disabled:opacity-50 disabled:cursor-not-allowed",
											)}
										>
											<span>{g.emoji}</span>
											{g.label}
										</button>
									))}
								</div>
							</div>

							{/* Language */}
							<div className="space-y-2">
								<SectionLabel>Language</SectionLabel>
								<div className="flex flex-wrap gap-2">
									{LANGUAGES.map((l) => (
										<button
											key={l.id}
											onClick={() => setLanguage(l.id)}
											disabled={isGenerating}
											className={cn(
												"flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-all",
												language === l.id
													? "border-afro-gold/50 bg-afro-gold/10 text-afro-gold"
													: "border-white/[0.07] text-zinc-500 hover:border-white/[0.14] hover:text-zinc-300",
												"disabled:opacity-50 disabled:cursor-not-allowed",
											)}
										>
											<span role="img" aria-label={l.label}>{l.flag}</span>
											{l.label}
										</button>
									))}
								</div>
							</div>

							{/* Energy slider */}
							<div className="space-y-3">
								<div className="flex items-center justify-between">
									<SectionLabel>Energy</SectionLabel>
									<span className="text-lg" role="img" aria-label={`Energy level ${energy}`}>
										{ENERGY_EMOJIS[energy - 1]}
									</span>
								</div>
								<Slider.Root
									className="relative flex items-center select-none touch-none w-full h-5"
									value={[energy]}
									onValueChange={([v]) => setEnergy(v ?? 6)}
									min={1}
									max={10}
									step={1}
									disabled={isGenerating}
									aria-label="Energy level"
								>
									<Slider.Track className="bg-dark-bg-elevated relative grow rounded-full h-1.5">
										<Slider.Range className="absolute bg-gradient-to-r from-afro-gold-600 to-afro-gold rounded-full h-full" />
									</Slider.Track>
									<Slider.Thumb className="block w-5 h-5 bg-afro-gold rounded-full shadow-lg shadow-afro-gold/30 focus:outline-none focus:ring-2 focus:ring-afro-gold/60 transition-transform hover:scale-110 cursor-grab active:cursor-grabbing" />
								</Slider.Root>
								<div className="flex justify-between text-[9px] font-mono text-zinc-700 uppercase tracking-wider px-0.5">
									<span>Mellow</span>
									<span>Electric</span>
								</div>
							</div>

							{/* Duration */}
							<div className="space-y-2">
								<SectionLabel>Duration</SectionLabel>
								<div className="grid grid-cols-4 gap-1.5">
									{DURATIONS.map((d) => (
										<button
											key={d.value}
											onClick={() => setDuration(d.value)}
											disabled={isGenerating}
											className={cn(
												"py-2 rounded-lg text-xs font-medium border transition-all",
												duration === d.value
													? "border-afro-gold/50 bg-afro-gold/10 text-afro-gold"
													: "border-white/[0.07] text-zinc-500 hover:border-white/[0.14] hover:text-zinc-300",
												"disabled:opacity-50",
											)}
										>
											{d.label}
										</button>
									))}
								</div>
							</div>

							{/* Advanced toggle */}
							<div className="border-t border-white/[0.05] pt-4">
								<button
									onClick={() => setShowAdvanced((v) => !v)}
									className="flex items-center gap-1.5 text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
								>
									{showAdvanced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
									Advanced settings
								</button>

								{showAdvanced && (
									<div className="mt-4 space-y-4 animate-slide-up">
										{/* BPM override */}
										<div className="space-y-1.5">
											<SectionLabel>BPM override (optional)</SectionLabel>
											<input
												type="number"
												value={bpmOverride}
												onChange={(e) => setBpmOverride(e.target.value)}
												disabled={isGenerating}
												min={60}
												max={200}
												placeholder="e.g. 120"
												className="w-full px-3 py-2 rounded-lg bg-dark-bg-elevated border border-white/[0.08] text-sm text-zinc-100 placeholder:text-zinc-700 focus:outline-none focus:ring-1 focus:ring-afro-gold/50 font-mono disabled:opacity-50"
											/>
										</div>
									</div>
								)}
							</div>
						</div>

						{/* Generate button — sticky at bottom of left panel */}
						<div className="p-5 sm:p-6 border-t border-white/[0.06] bg-dark-bg-primary/80 backdrop-blur-xl">
							{isGenerating ? (
								<button
									onClick={cancelGeneration}
									className="w-full py-4 rounded-xl border border-red-500/30 bg-red-500/10 text-red-400 text-sm font-semibold hover:bg-red-500/20 transition-all"
								>
									Cancel generation
								</button>
							) : (
								<button
									onClick={handleGenerate}
									disabled={!prompt.trim()}
									className={cn(
										"w-full py-4 rounded-xl font-semibold text-dark-bg-primary text-base transition-all duration-200",
										"bg-afro-gold hover:bg-afro-gold-300 disabled:opacity-40 disabled:cursor-not-allowed",
										"flex items-center justify-center gap-2.5",
										prompt.trim() ? "animate-pulse-gold shadow-lg shadow-afro-gold/20" : "",
									)}
								>
									<Sparkles className="w-5 h-5" />
									Generate Track
								</button>
							)}

							{/* Credits info */}
							{user && (
								<p className="text-center text-[10px] text-zinc-700 mt-2">
									{user.subscriptionTier === "free"
										? `${user.creditsRemaining} free tracks remaining`
										: `${user.subscriptionTier} plan`}
								</p>
							)}
						</div>
					</aside>

					{/* ===== RIGHT PANEL — Output ===== */}
					<section className="flex-1 flex flex-col min-h-0 overflow-y-auto">
						{/* Empty state */}
						{!isGenerating && !currentTrack && !error && (
							<div className="flex-1 flex flex-col items-center justify-center p-8 text-center gap-6">
								<div className="relative">
									{/* Concentric ring decoration */}
									<div className="absolute inset-0 -m-8 rounded-full border border-afro-gold/5" />
									<div className="absolute inset-0 -m-16 rounded-full border border-afro-gold/[0.03]" />
									<div className="w-20 h-20 rounded-full bg-afro-gold/8 border border-afro-gold/20 flex items-center justify-center">
										<Music2 className="w-9 h-9 text-afro-gold/50" />
									</div>
								</div>
								<div className="space-y-2 max-w-xs">
									<p className="text-zinc-400 font-medium">Your track will appear here</p>
									<p className="text-xs text-zinc-700 leading-relaxed">
										Describe your vibe, pick your genre and language, then hit Generate
									</p>
								</div>

								{/* Sample waveform decoration */}
								<div className="flex items-end gap-1 h-12 opacity-10">
									{Array.from({ length: 32 }).map((_, i) => (
										<span
											key={i}
											className="w-1 rounded-full bg-afro-gold"
											style={{
												height: `${20 + Math.sin(i * 0.7) * 30 + Math.cos(i * 0.3) * 20}%`,
											}}
										/>
									))}
								</div>
							</div>
						)}

						{/* Error state */}
						{error && !isGenerating && (
							<div className="flex-1 flex flex-col items-center justify-center p-8 text-center gap-4">
								<div className="w-14 h-14 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center">
									<AlertCircle className="w-7 h-7 text-red-400" />
								</div>
								<div className="space-y-1">
									<p className="text-zinc-300 font-medium">Generation failed</p>
									<p className="text-xs text-zinc-600 max-w-xs">{error}</p>
								</div>
								<button
									onClick={reset}
									className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-dark-bg-elevated border border-white/[0.08] text-sm text-zinc-400 hover:text-zinc-200 hover:border-white/[0.16] transition-all"
								>
									<RefreshCw className="w-3.5 h-3.5" />
									Try again
								</button>
							</div>
						)}

						{/* Generation in progress */}
						{showProgress && (
							<div className="flex-1 flex flex-col items-center justify-center p-8 gap-8">
								<div className="w-full max-w-md space-y-2">
									<GenerationProgress
										status={jobStatus}
										progressPercent={progressPercent}
										statusMessage={statusMessage}
									/>
								</div>
								<p className="text-xs text-zinc-700 text-center max-w-xs leading-relaxed">
									Gbẹdu&apos;s AI is composing your track. This typically takes 30–90 seconds depending on duration.
								</p>
							</div>
						)}

						{/* Track ready */}
						{currentTrack && showPlayer && (
							<div className="flex-1 p-5 sm:p-8 flex flex-col gap-6 animate-fade-in">
								{/* Track header */}
								<div className="flex items-start justify-between gap-4">
									<div className="space-y-2">
										<h2 className="font-display text-2xl sm:text-3xl font-bold text-zinc-100 leading-tight">
											{currentTrack.title}
										</h2>
										<div className="flex flex-wrap items-center gap-2">
											<span
												className={cn(
													"text-xs font-medium px-2 py-0.5 rounded-full border",
													GENRE_BADGE_COLORS[currentTrack.subGenre] ?? "bg-zinc-800 text-zinc-400 border-zinc-700",
												)}
											>
												{subGenreLabel(currentTrack.subGenre)}
											</span>
											<span className="text-sm" role="img" aria-label={currentTrack.language}>
												{languageFlag(currentTrack.language)}
											</span>
											{currentTrack.bpm && (
												<span className="font-mono text-xs text-zinc-500 bg-dark-bg-elevated px-2 py-0.5 rounded-full border border-white/[0.06]">
													{currentTrack.bpm} BPM
												</span>
											)}
											{currentTrack.musicalKey && (
												<span className="font-mono text-xs text-zinc-500 bg-dark-bg-elevated px-2 py-0.5 rounded-full border border-white/[0.06]">
													{currentTrack.musicalKey}
												</span>
											)}
											<span className="font-mono text-xs text-zinc-600">
												{formatDuration(currentTrack.durationSeconds)}
											</span>
										</div>
									</div>
								</div>

								{/* Audio player */}
								<div className="glass-gold rounded-2xl p-5">
									<AudioPlayer
										src={currentTrack.audioUrl ?? currentTrack.previewUrl ?? ""}
										showWaveform
									/>
								</div>

								{/* Action buttons */}
								<div className="flex flex-wrap gap-2">
									<Tooltip.Root>
										<Tooltip.Trigger asChild>
											<button
												onClick={handleDownload}
												disabled={isDownloading}
												className={cn(
													"flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all",
													canDownload
														? "bg-afro-gold text-dark-bg-primary hover:bg-afro-gold-300"
														: "bg-dark-bg-elevated border border-white/[0.08] text-zinc-400 hover:text-zinc-200",
												)}
											>
												<Download className="w-4 h-4" />
												{canDownload ? "Download MP3" : "Download"}
												{!canDownload && <span className="text-[10px] text-afro-gold">PRO</span>}
											</button>
										</Tooltip.Trigger>
										{!canDownload && (
											<Tooltip.Portal>
												<Tooltip.Content
													className="rounded-lg bg-dark-bg-card border border-white/[0.08] px-3 py-1.5 text-xs text-zinc-300 shadow-xl"
													sideOffset={6}
												>
													Upgrade to download tracks
													<Tooltip.Arrow className="fill-dark-bg-card" />
												</Tooltip.Content>
											</Tooltip.Portal>
										)}
									</Tooltip.Root>

									<button
										onClick={handleShare}
										className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium bg-dark-bg-elevated border border-white/[0.08] text-zinc-400 hover:text-zinc-200 hover:border-white/[0.16] transition-all"
									>
										{copied ? (
											<><Check className="w-4 h-4 text-afro-green" /> Copied!</>
										) : (
											<><Share2 className="w-4 h-4" /> Share</>
										)}
									</button>

									<button
										onClick={() => {}}
										className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium bg-dark-bg-elevated border border-white/[0.08] text-zinc-400 hover:text-zinc-200 hover:border-white/[0.16] transition-all"
									>
										<BookmarkPlus className="w-4 h-4" />
										Save to Library
									</button>

									<Tooltip.Root>
										<Tooltip.Trigger asChild>
											<button
												onClick={handleGetStems}
												className={cn(
													"flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all",
													canGetStems
														? "bg-dark-bg-elevated border border-white/[0.08] text-zinc-400 hover:text-zinc-200 hover:border-white/[0.16]"
														: "bg-dark-bg-elevated border border-white/[0.08] text-zinc-600",
												)}
											>
												<Music2 className="w-4 h-4" />
												Get Stems
												{!canGetStems && <span className="text-[10px] text-purple-400">PRO</span>}
											</button>
										</Tooltip.Trigger>
										{!canGetStems && (
											<Tooltip.Portal>
												<Tooltip.Content
													className="rounded-lg bg-dark-bg-card border border-white/[0.08] px-3 py-1.5 text-xs text-zinc-300 shadow-xl"
													sideOffset={6}
												>
													Stems available on Pro and Label plans
													<Tooltip.Arrow className="fill-dark-bg-card" />
												</Tooltip.Content>
											</Tooltip.Portal>
										)}
									</Tooltip.Root>

									<button
										onClick={() => {
											reset()
										}}
										className="ml-auto flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium bg-dark-bg-elevated border border-white/[0.08] text-zinc-500 hover:text-zinc-300 hover:border-white/[0.16] transition-all"
									>
										<RefreshCw className="w-4 h-4" />
										Regenerate
									</button>
								</div>

								{/* Share preview card */}
								<div className="glass rounded-xl p-4 border border-white/[0.06]">
									<div className="flex items-center justify-between mb-3">
										<span className="text-xs font-mono uppercase tracking-widest text-zinc-600">
											Share card
										</span>
										<button
											onClick={handleShare}
											className="flex items-center gap-1 text-xs text-zinc-600 hover:text-afro-gold transition-colors"
										>
											<Copy className="w-3 h-3" />
											Copy link
										</button>
									</div>
									<div className="rounded-lg bg-dark-bg-elevated p-3 flex items-center gap-3">
										<div className="w-10 h-10 rounded-md bg-gradient-to-br from-afro-gold/20 to-afro-gold/5 border border-afro-gold/20 flex items-center justify-center shrink-0">
											<Music2 className="w-5 h-5 text-afro-gold/60" />
										</div>
										<div className="min-w-0">
											<p className="text-sm font-medium text-zinc-200 truncate">{currentTrack.title}</p>
											<p className="text-xs text-zinc-600">
												{subGenreLabel(currentTrack.subGenre)} · {languageFlag(currentTrack.language)} · via Gbẹdu
											</p>
										</div>
									</div>
								</div>
							</div>
						)}
					</section>
				</main>
			</div>

			{/* Upgrade modal */}
			<UpgradeModal open={showUpgrade} onOpenChange={setShowUpgrade} />
		</Tooltip.Provider>
	)
}
