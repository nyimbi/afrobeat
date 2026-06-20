"use client"

import { useState, useCallback, useEffect } from "react"
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { Search, SlidersHorizontal, Music2, Loader2, Sparkles } from "lucide-react"
import { Navbar } from "@/components/layout/navbar"
import { TrackCard } from "@/components/ui/track-card"
import { AudioPlayer } from "@/components/ui/audio-player"
import { cn, subGenreLabel } from "@/lib/utils"
import { api } from "@/lib/api"
import type { Track, SubGenre, Language } from "@/lib/types"

const SUB_GENRES: { id: SubGenre; label: string }[] = [
	{ id: "afrobeats",     label: "Afrobeats" },
	{ id: "afropop",       label: "Afropop" },
	{ id: "afrofusion",    label: "Afrofusion" },
	{ id: "alte",          label: "Alte" },
	{ id: "highlife",      label: "Highlife" },
	{ id: "amapiano_cross",label: "Amapiano" },
	{ id: "uk_afrobeats",  label: "UK Afrobeats" },
	{ id: "bongo_flava",   label: "Bongo Flava" },
	{ id: "soukous",       label: "Soukous" },
	{ id: "mbalax",        label: "Mbalax" },
	{ id: "gengetone",     label: "Gengetone" },
	{ id: "benga",         label: "Benga" },
	{ id: "taarab",        label: "Taarab" },
	{ id: "soca",          label: "Soca" },
	{ id: "calypso",       label: "Calypso" },
	{ id: "afro_soca",     label: "Afro-Soca" },
]

const LANGUAGES: { id: Language; label: string }[] = [
	{ id: "english", label: "English" },
	{ id: "pidgin",  label: "Pidgin" },
	{ id: "yoruba",  label: "Yoruba" },
	{ id: "igbo",    label: "Igbo" },
	{ id: "twi",     label: "Twi" },
	{ id: "swahili", label: "Swahili" },
	{ id: "lingala", label: "Lingala" },
	{ id: "zulu",    label: "Zulu" },
	{ id: "mix",     label: "Mix" },
]

const PAGE_SIZE = 24

export default function LibraryPage() {
	const queryClient = useQueryClient()
	const [search, setSearch] = useState("")
	const [activeSearch, setActiveSearch] = useState("")
	const [subGenreFilter, setSubGenreFilter] = useState<SubGenre | null>(null)
	const [languageFilter, setLanguageFilter] = useState<Language | null>(null)
	const [playingTrack, setPlayingTrack] = useState<Track | null>(null)
	const [showFilters, setShowFilters] = useState(false)

	const {
		data,
		fetchNextPage,
		hasNextPage,
		isFetchingNextPage,
		isLoading,
		isError,
	} = useInfiniteQuery({
		queryKey: ["tracks", activeSearch, subGenreFilter, languageFilter],
		queryFn: ({ pageParam = 1 }) =>
			api.tracks.getTracks({
				page: pageParam as number,
				pageSize: PAGE_SIZE,
				search: activeSearch || undefined,
				subGenre: subGenreFilter ?? undefined,
				language: languageFilter ?? undefined,
			}),
		getNextPageParam: (lastPage) =>
			lastPage.hasMore ? lastPage.page + 1 : undefined,
		initialPageParam: 1,
	})

	const deleteMutation = useMutation({
		mutationFn: (trackId: string) => api.tracks.deleteTrack(trackId),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["tracks"] })
		},
	})

	const downloadMutation = useMutation({
		mutationFn: async (trackId: string) => {
			const { url } = await api.tracks.getDownloadUrl(trackId, "mp3")
			const a = document.createElement("a")
			a.href = url
			a.download = `track-${trackId}.mp3`
			a.click()
		},
	})

	const allTracks = data?.pages.flatMap((p) => p.items) ?? []
	const totalCount = data?.pages[0]?.total ?? 0

	// Debounced search — fires 400ms after the user stops typing
	useEffect(() => {
		const t = setTimeout(() => setActiveSearch(search), 400)
		return () => clearTimeout(t)
	}, [search])

	const handleSearch = useCallback((e: React.FormEvent) => {
		e.preventDefault()
		setActiveSearch(search)
	}, [search])

	const handlePlay = useCallback((track: Track) => {
		setPlayingTrack((prev) => (prev?.id === track.id ? null : track))
	}, [])

	return (
		<div className="min-h-dvh bg-dark-bg-primary flex flex-col">
			<Navbar />

			<main className="flex-1 pt-16 pb-16 sm:pb-0">
				{/* Sticky header bar */}
				<div className="sticky top-16 z-30 bg-dark-bg-primary/90 backdrop-blur-xl border-b border-white/[0.06]">
					<div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 space-y-3">
						{/* Title + count */}
						<div className="flex items-center justify-between">
							<div>
								<h1 className="font-display text-xl font-bold text-zinc-100">
									My Library
								</h1>
								{!isLoading && (
									<p className="text-xs text-zinc-600 mt-0.5">
										{totalCount} {totalCount === 1 ? "track" : "tracks"}
									</p>
								)}
							</div>
							<button
								onClick={() => setShowFilters((v) => !v)}
								className={cn(
									"flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
									showFilters
										? "border-afro-gold/40 bg-afro-gold/8 text-afro-gold"
										: "border-white/[0.08] text-zinc-500 hover:text-zinc-300 hover:border-white/[0.16]",
								)}
							>
								<SlidersHorizontal className="w-3.5 h-3.5" />
								Filters
							</button>
						</div>

						{/* Search */}
						<form onSubmit={handleSearch} className="relative">
							<Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-600" />
							<input
								type="search"
								value={search}
								onChange={(e) => setSearch(e.target.value)}
								placeholder="Search your tracks..."
								className="w-full pl-9 pr-4 py-2 rounded-lg bg-dark-bg-elevated border border-white/[0.08] text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-afro-gold/50 transition-all"
							/>
						</form>

						{/* Filter chips */}
						{showFilters && (
							<div className="flex flex-wrap gap-3 animate-slide-up">
								<div className="flex flex-wrap gap-1.5">
									<span className="text-[10px] uppercase tracking-widest text-zinc-700 self-center mr-1">Genre</span>
									<button
										onClick={() => setSubGenreFilter(null)}
										className={cn(
											"px-2.5 py-1 rounded-full text-xs border transition-all",
											subGenreFilter === null
												? "border-afro-gold/40 bg-afro-gold/10 text-afro-gold"
												: "border-white/[0.07] text-zinc-600 hover:text-zinc-400",
										)}
									>
										All
									</button>
									{SUB_GENRES.map((g) => (
										<button
											key={g.id}
											onClick={() => setSubGenreFilter(subGenreFilter === g.id ? null : g.id)}
											className={cn(
												"px-2.5 py-1 rounded-full text-xs border transition-all",
												subGenreFilter === g.id
													? "border-afro-gold/40 bg-afro-gold/10 text-afro-gold"
													: "border-white/[0.07] text-zinc-600 hover:text-zinc-400",
											)}
										>
											{g.label}
										</button>
									))}
								</div>

								<div className="w-px bg-white/[0.06] self-stretch" />

								<div className="flex flex-wrap gap-1.5">
									<span className="text-[10px] uppercase tracking-widest text-zinc-700 self-center mr-1">Language</span>
									<button
										onClick={() => setLanguageFilter(null)}
										className={cn(
											"px-2.5 py-1 rounded-full text-xs border transition-all",
											languageFilter === null
												? "border-afro-gold/40 bg-afro-gold/10 text-afro-gold"
												: "border-white/[0.07] text-zinc-600 hover:text-zinc-400",
										)}
									>
										All
									</button>
									{LANGUAGES.map((l) => (
										<button
											key={l.id}
											onClick={() => setLanguageFilter(languageFilter === l.id ? null : l.id)}
											className={cn(
												"px-2.5 py-1 rounded-full text-xs border transition-all",
												languageFilter === l.id
													? "border-afro-gold/40 bg-afro-gold/10 text-afro-gold"
													: "border-white/[0.07] text-zinc-600 hover:text-zinc-400",
											)}
										>
											{l.label}
										</button>
									))}
								</div>
							</div>
						)}
					</div>
				</div>

				{/* Content area */}
				<div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
					{/* Loading skeleton */}
					{isLoading && (
						<div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-4">
							{Array.from({ length: 12 }).map((_, i) => (
								<div key={i} className="rounded-xl overflow-hidden">
									<div className="aspect-square skeleton" />
									<div className="p-3 space-y-2">
										<div className="h-3 skeleton rounded" />
										<div className="h-2 w-2/3 skeleton rounded" />
									</div>
								</div>
							))}
						</div>
					)}

					{/* Error state */}
					{isError && (
						<div className="text-center py-24 space-y-3">
							<p className="text-zinc-400">Couldn&apos;t load your library</p>
							<p className="text-xs text-zinc-600">Check your connection and try again</p>
						</div>
					)}

					{/* Empty state */}
					{!isLoading && !isError && allTracks.length === 0 && (
						<div className="text-center py-24 space-y-5">
							<div className="w-16 h-16 rounded-2xl bg-dark-bg-elevated border border-white/[0.06] flex items-center justify-center mx-auto">
								<Music2 className="w-8 h-8 text-zinc-700" />
							</div>
							<div className="space-y-1">
								<p className="text-zinc-400 font-medium">
									{activeSearch || subGenreFilter || languageFilter
										? "No tracks match your filters"
										: "Your library is empty"}
								</p>
								<p className="text-xs text-zinc-600">
									{activeSearch || subGenreFilter || languageFilter
										? "Try adjusting your search or filters"
										: "Generate your first track in the studio"}
								</p>
							</div>
							{!activeSearch && !subGenreFilter && !languageFilter && (
								<Link
									href="/studio"
									className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-afro-gold text-dark-bg-primary text-sm font-semibold hover:bg-afro-gold-300 transition-colors"
								>
									<Sparkles className="w-4 h-4" />
									Open Studio
								</Link>
							)}
						</div>
					)}

					{/* Track grid */}
					{!isLoading && allTracks.length > 0 && (
						<div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4">
							{allTracks.map((track) => (
								<TrackCard
									key={track.id}
									track={track}
									isPlaying={playingTrack?.id === track.id}
									onPlay={handlePlay}
									onDelete={(id) => deleteMutation.mutate(id)}
									onDownload={(id) => downloadMutation.mutate(id)}
									onShare={(t) => {
										const url = `${window.location.origin}/track/${t.id}`
										navigator.clipboard.writeText(url)
									}}
								/>
							))}
						</div>
					)}

					{/* Load more */}
					{hasNextPage && (
						<div className="flex justify-center mt-10">
							<button
								onClick={() => fetchNextPage()}
								disabled={isFetchingNextPage}
								className="flex items-center gap-2 px-6 py-2.5 rounded-xl border border-white/[0.08] bg-dark-bg-elevated text-sm text-zinc-400 hover:text-zinc-200 hover:border-white/[0.16] transition-all disabled:opacity-60"
							>
								{isFetchingNextPage ? (
									<Loader2 className="w-4 h-4 animate-spin" />
								) : (
									"Load more"
								)}
							</button>
						</div>
					)}
				</div>
			</main>

			{/* Mini player sticky at bottom when a track is playing */}
			{playingTrack?.audioUrl && (
				<div className="fixed bottom-16 sm:bottom-0 inset-x-0 z-40 bg-dark-bg-secondary/95 backdrop-blur-xl border-t border-white/[0.08] px-4 sm:px-6 py-3">
					<div className="max-w-7xl mx-auto flex items-center gap-4">
						<div className="shrink-0 text-left min-w-0 w-40 hidden sm:block">
							<p className="text-sm font-medium text-zinc-100 truncate">{playingTrack.title}</p>
							<p className="text-xs text-zinc-600">{subGenreLabel(playingTrack.subGenre)}</p>
						</div>
						<div className="flex-1">
							<AudioPlayer
								src={playingTrack.audioUrl}
								mini
								showWaveform={false}
								onEnded={() => setPlayingTrack(null)}
							/>
						</div>
					</div>
				</div>
			)}
		</div>
	)
}
