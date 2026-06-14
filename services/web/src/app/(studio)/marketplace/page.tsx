"use client"

import { useState } from "react"
import { useInfiniteQuery, useMutation } from "@tanstack/react-query"
import * as Slider from "@radix-ui/react-slider"
import {
	ShoppingBag,
	SlidersHorizontal,
	Play,
	Pause,
	Music2,
	Loader2,
	X,
} from "lucide-react"
import { Navbar } from "@/components/layout/navbar"
import { AudioPlayer } from "@/components/ui/audio-player"
import { cn, subGenreLabel } from "@/lib/utils"
import { api } from "@/lib/api"
import type { BeatListing, SubGenre } from "@/lib/types"

const SUB_GENRES: { id: SubGenre; label: string; emoji: string }[] = [
	{ id: "afropop", label: "Afropop", emoji: "🌟" },
	{ id: "afrofusion", label: "Afrofusion", emoji: "🔥" },
	{ id: "alte", label: "Alte", emoji: "🎸" },
	{ id: "amapiano", label: "Amapiano", emoji: "🪗" },
	{ id: "uk_afrobeats", label: "UK Afrobeats", emoji: "👑" },
]

const MUSICAL_KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

const PAGE_SIZE = 20

function BeatCard({
	beat,
	isPlaying,
	onPlay,
	onPurchase,
}: {
	beat: BeatListing
	isPlaying: boolean
	onPlay: (beat: BeatListing) => void
	onPurchase: (beat: BeatListing) => void
}) {
	return (
		<div className="group rounded-xl bg-dark-bg-card border border-white/[0.06] hover:border-afro-gold/20 transition-all duration-300 overflow-hidden">
			{/* Top — BPM/key/genre info bar */}
			<div className="flex items-center gap-2 px-3 pt-3 pb-2">
				<span className="font-mono text-[10px] text-zinc-600 bg-dark-bg-elevated px-1.5 py-0.5 rounded border border-white/[0.05]">
					{beat.bpm} BPM
				</span>
				<span className="font-mono text-[10px] text-zinc-600 bg-dark-bg-elevated px-1.5 py-0.5 rounded border border-white/[0.05]">
					{beat.musicalKey}
				</span>
				<span className="text-[10px] text-zinc-600 ml-auto">{subGenreLabel(beat.subGenre)}</span>
			</div>

			{/* Title and producer */}
			<div className="px-3 pb-2">
				<h3 className="text-sm font-semibold text-zinc-100 truncate leading-tight">{beat.title}</h3>
				<p className="text-xs text-zinc-600 mt-0.5">by {beat.producerName}</p>
			</div>

			{/* Mini player area */}
			<div className="px-3 pb-3">
				<div className="flex items-center gap-2 bg-dark-bg-elevated rounded-lg px-2 py-1.5">
					<button
						onClick={() => onPlay(beat)}
						className="w-7 h-7 rounded-full bg-afro-gold/10 border border-afro-gold/30 flex items-center justify-center text-afro-gold hover:bg-afro-gold/20 transition-colors shrink-0"
						aria-label={isPlaying ? "Pause" : "Play preview"}
					>
						{isPlaying ? (
							<Pause className="w-3 h-3" />
						) : (
							<Play className="w-3 h-3 translate-x-px" />
						)}
					</button>

					{/* Fake static waveform bars — real ones load when playing */}
					<div className="flex-1 flex items-end gap-px h-5">
						{Array.from({ length: 28 }).map((_, i) => (
							<span
								key={i}
								className={cn(
									"flex-1 rounded-sm transition-colors",
									isPlaying ? "bg-afro-gold" : "bg-zinc-700",
								)}
								style={{
									height: `${25 + Math.sin(i * 0.8 + beat.id.charCodeAt(0)) * 30 + Math.cos(i * 0.4) * 20}%`,
									animation: isPlaying ? `waveform ${0.7 + (i % 4) * 0.15}s ease-in-out infinite` : "none",
									animationDelay: `${(i * 0.05) % 1}s`,
								}}
							/>
						))}
					</div>
				</div>
			</div>

			{/* Price + purchase */}
			<div className="px-3 pb-3 flex items-center justify-between">
				<div>
					<div className="text-base font-bold text-zinc-100">
						${beat.price}
						<span className="text-xs font-normal text-zinc-600 ml-1">USD</span>
					</div>
					<div className="text-[10px] text-zinc-700 capitalize">{beat.licenseType} license</div>
				</div>

				<button
					onClick={() => onPurchase(beat)}
					className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-afro-gold text-dark-bg-primary text-xs font-semibold hover:bg-afro-gold-300 transition-colors"
				>
					<ShoppingBag className="w-3 h-3" />
					Buy
				</button>
			</div>
		</div>
	)
}

export default function MarketplacePage() {
	const [subGenreFilter, setSubGenreFilter] = useState<SubGenre | null>(null)
	const [keyFilter, setKeyFilter] = useState<string | null>(null)
	const [bpmRange, setBpmRange] = useState<[number, number]>([60, 180])
	const [priceMax, setPriceMax] = useState(100)
	const [showSidebar, setShowSidebar] = useState(false)
	const [playingBeat, setPlayingBeat] = useState<BeatListing | null>(null)

	const {
		data,
		fetchNextPage,
		hasNextPage,
		isFetchingNextPage,
		isLoading,
		isError,
	} = useInfiniteQuery({
		queryKey: ["beats", subGenreFilter, keyFilter, bpmRange, priceMax],
		queryFn: ({ pageParam = 1 }) =>
			api.marketplace.getBeats({
				page: pageParam as number,
				pageSize: PAGE_SIZE,
				subGenre: subGenreFilter ?? undefined,
				key: keyFilter ?? undefined,
				bpmMin: bpmRange[0],
				bpmMax: bpmRange[1],
				priceMax,
			}),
		getNextPageParam: (last) => (last.hasMore ? last.page + 1 : undefined),
		initialPageParam: 1,
	})

	const purchaseMutation = useMutation({
		mutationFn: (beat: BeatListing) =>
			api.marketplace.purchaseBeat(beat.id, "stripe"),
		onSuccess: (res) => {
			window.location.href = res.checkoutUrl
		},
	})

	const allBeats = data?.pages.flatMap((p) => p.items) ?? []
	const totalCount = data?.pages[0]?.total ?? 0

	function handlePlay(beat: BeatListing) {
		setPlayingBeat((prev) => (prev?.id === beat.id ? null : beat))
	}

	const activeFilterCount = [
		subGenreFilter,
		keyFilter,
		bpmRange[0] !== 60 || bpmRange[1] !== 180 ? "bpm" : null,
		priceMax !== 100 ? "price" : null,
	].filter(Boolean).length

	return (
		<div className="min-h-dvh bg-dark-bg-primary flex flex-col">
			<Navbar />

			<main className="flex-1 pt-16 flex flex-col lg:flex-row">
				{/* ===== FILTER SIDEBAR ===== */}
				<aside
					className={cn(
						"w-full lg:w-64 xl:w-72 shrink-0 border-b lg:border-b-0 lg:border-r border-white/[0.06]",
						"lg:sticky lg:top-16 lg:h-[calc(100dvh-4rem)] lg:overflow-y-auto",
						showSidebar ? "block" : "hidden lg:block",
					)}
				>
					<div className="p-5 space-y-6">
						<div className="flex items-center justify-between">
							<h2 className="font-display text-sm font-bold text-zinc-300">Filters</h2>
							{activeFilterCount > 0 && (
								<button
									onClick={() => {
										setSubGenreFilter(null)
										setKeyFilter(null)
										setBpmRange([60, 180])
										setPriceMax(100)
									}}
									className="text-xs text-afro-gold hover:underline"
								>
									Clear all
								</button>
							)}
						</div>

						{/* Genre */}
						<div className="space-y-2">
							<span className="text-[10px] font-mono uppercase tracking-widest text-zinc-600">
								Sub-genre
							</span>
							<div className="space-y-1">
								{SUB_GENRES.map((g) => (
									<button
										key={g.id}
										onClick={() => setSubGenreFilter(subGenreFilter === g.id ? null : g.id)}
										className={cn(
											"w-full text-left flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs transition-all",
											subGenreFilter === g.id
												? "bg-afro-gold/10 text-afro-gold"
												: "text-zinc-500 hover:text-zinc-300 hover:bg-white/[0.04]",
										)}
									>
										<span>{g.emoji}</span>
										{g.label}
									</button>
								))}
							</div>
						</div>

						{/* Key */}
						<div className="space-y-2">
							<span className="text-[10px] font-mono uppercase tracking-widest text-zinc-600">
								Musical key
							</span>
							<div className="flex flex-wrap gap-1">
								{MUSICAL_KEYS.map((k) => (
									<button
										key={k}
										onClick={() => setKeyFilter(keyFilter === k ? null : k)}
										className={cn(
											"w-9 h-9 rounded-lg text-xs font-mono font-medium border transition-all",
											keyFilter === k
												? "border-afro-gold/50 bg-afro-gold/10 text-afro-gold"
												: "border-white/[0.07] text-zinc-600 hover:border-white/[0.16] hover:text-zinc-300",
										)}
									>
										{k}
									</button>
								))}
							</div>
						</div>

						{/* BPM range */}
						<div className="space-y-3">
							<div className="flex items-center justify-between">
								<span className="text-[10px] font-mono uppercase tracking-widest text-zinc-600">
									BPM range
								</span>
								<span className="font-mono text-[10px] text-zinc-500">
									{bpmRange[0]}–{bpmRange[1]}
								</span>
							</div>
							<Slider.Root
								className="relative flex items-center select-none touch-none w-full h-4"
								value={bpmRange}
								onValueChange={(v) => setBpmRange([v[0] ?? 60, v[1] ?? 180])}
								min={60}
								max={200}
								step={5}
								minStepsBetweenThumbs={2}
							>
								<Slider.Track className="bg-dark-bg-elevated relative grow rounded-full h-1">
									<Slider.Range className="absolute bg-afro-gold rounded-full h-full" />
								</Slider.Track>
								<Slider.Thumb className="block w-4 h-4 bg-afro-gold rounded-full shadow-md focus:outline-none focus:ring-2 focus:ring-afro-gold/60" />
								<Slider.Thumb className="block w-4 h-4 bg-afro-gold rounded-full shadow-md focus:outline-none focus:ring-2 focus:ring-afro-gold/60" />
							</Slider.Root>
						</div>

						{/* Max price */}
						<div className="space-y-3">
							<div className="flex items-center justify-between">
								<span className="text-[10px] font-mono uppercase tracking-widest text-zinc-600">
									Max price
								</span>
								<span className="font-mono text-[10px] text-zinc-500">${priceMax}</span>
							</div>
							<Slider.Root
								className="relative flex items-center select-none touch-none w-full h-4"
								value={[priceMax]}
								onValueChange={([v]) => setPriceMax(v ?? 100)}
								min={5}
								max={500}
								step={5}
							>
								<Slider.Track className="bg-dark-bg-elevated relative grow rounded-full h-1">
									<Slider.Range className="absolute bg-afro-gold rounded-full h-full" />
								</Slider.Track>
								<Slider.Thumb className="block w-4 h-4 bg-afro-gold rounded-full shadow-md focus:outline-none focus:ring-2 focus:ring-afro-gold/60" />
							</Slider.Root>
						</div>
					</div>
				</aside>

				{/* ===== MAIN CONTENT ===== */}
				<div className="flex-1 flex flex-col min-w-0">
					{/* Sticky top bar */}
					<div className="sticky top-16 z-20 bg-dark-bg-primary/90 backdrop-blur-xl border-b border-white/[0.06] px-4 sm:px-6 py-3 flex items-center justify-between gap-4">
						<div>
							<h1 className="font-display text-lg font-bold text-zinc-100">
								Beat Marketplace
							</h1>
							{!isLoading && (
								<p className="text-xs text-zinc-600">
									{totalCount.toLocaleString()} beats
									{activeFilterCount > 0 ? ` · ${activeFilterCount} filter${activeFilterCount > 1 ? "s" : ""} active` : ""}
								</p>
							)}
						</div>

						<button
							onClick={() => setShowSidebar((v) => !v)}
							className={cn(
								"lg:hidden flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
								showSidebar
									? "border-afro-gold/40 bg-afro-gold/8 text-afro-gold"
									: "border-white/[0.08] text-zinc-500",
							)}
						>
							{showSidebar ? <X className="w-3.5 h-3.5" /> : <SlidersHorizontal className="w-3.5 h-3.5" />}
							{showSidebar ? "Close" : "Filters"}
							{activeFilterCount > 0 && (
								<span className="w-4 h-4 rounded-full bg-afro-gold text-dark-bg-primary text-[9px] font-bold flex items-center justify-center">
									{activeFilterCount}
								</span>
							)}
						</button>
					</div>

					<div className="flex-1 p-4 sm:p-6">
						{/* Loading skeleton */}
						{isLoading && (
							<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
								{Array.from({ length: 12 }).map((_, i) => (
									<div key={i} className="rounded-xl overflow-hidden bg-dark-bg-card border border-white/[0.06] p-3 space-y-3">
										<div className="h-3 skeleton rounded w-2/3" />
										<div className="h-2 skeleton rounded w-1/2" />
										<div className="h-8 skeleton rounded-lg" />
										<div className="h-6 skeleton rounded" />
									</div>
								))}
							</div>
						)}

						{/* Error */}
						{isError && (
							<div className="text-center py-24 space-y-2">
								<p className="text-zinc-400">Couldn&apos;t load beats</p>
								<p className="text-xs text-zinc-600">Check your connection and try again</p>
							</div>
						)}

						{/* Empty */}
						{!isLoading && !isError && allBeats.length === 0 && (
							<div className="text-center py-24 space-y-4">
								<div className="w-16 h-16 rounded-2xl bg-dark-bg-elevated border border-white/[0.06] flex items-center justify-center mx-auto">
									<Music2 className="w-8 h-8 text-zinc-700" />
								</div>
								<p className="text-zinc-500">No beats match your filters</p>
							</div>
						)}

						{/* Beat grid */}
						{!isLoading && allBeats.length > 0 && (
							<>
								<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
									{allBeats.map((beat) => (
										<BeatCard
											key={beat.id}
											beat={beat}
											isPlaying={playingBeat?.id === beat.id}
											onPlay={handlePlay}
											onPurchase={(b) => purchaseMutation.mutate(b)}
										/>
									))}
								</div>

								{hasNextPage && (
									<div className="flex justify-center mt-10">
										<button
											onClick={() => fetchNextPage()}
											disabled={isFetchingNextPage}
											className="flex items-center gap-2 px-6 py-2.5 rounded-xl border border-white/[0.08] bg-dark-bg-elevated text-sm text-zinc-400 hover:text-zinc-200 transition-all disabled:opacity-60"
										>
											{isFetchingNextPage ? (
												<Loader2 className="w-4 h-4 animate-spin" />
											) : (
												"Load more beats"
											)}
										</button>
									</div>
								)}
							</>
						)}
					</div>
				</div>
			</main>

			{/* Playing beat mini-player */}
			{playingBeat?.previewUrl && (
				<div className="fixed bottom-0 inset-x-0 z-40 bg-dark-bg-secondary/95 backdrop-blur-xl border-t border-white/[0.08] px-4 sm:px-6 py-3">
					<div className="max-w-7xl mx-auto flex items-center gap-4">
						<div className="shrink-0 min-w-0 w-44 hidden sm:block">
							<p className="text-sm font-medium text-zinc-100 truncate">{playingBeat.title}</p>
							<p className="text-xs text-zinc-600">
								{playingBeat.producerName} · {playingBeat.bpm} BPM
							</p>
						</div>
						<div className="flex-1">
							<AudioPlayer
								src={playingBeat.previewUrl}
								mini
								showWaveform={false}
								onEnded={() => setPlayingBeat(null)}
							/>
						</div>
						<button
							onClick={() => purchaseMutation.mutate(playingBeat)}
							className="shrink-0 flex items-center gap-1.5 px-4 py-2 rounded-lg bg-afro-gold text-dark-bg-primary text-sm font-semibold hover:bg-afro-gold-300 transition-colors"
						>
							<ShoppingBag className="w-4 h-4" />
							Buy ${playingBeat.price}
						</button>
					</div>
				</div>
			)}
		</div>
	)
}
