"use client"

import { useState } from "react"
import * as DropdownMenu from "@radix-ui/react-dropdown-menu"
import {
	Play,
	Pause,
	Download,
	Share2,
	Trash2,
	MoreHorizontal,
	Headphones,
} from "lucide-react"
import { cn, formatDuration, formatPlayCount, formatRelativeDate, subGenreLabel, languageFlag } from "@/lib/utils"
import type { Track } from "@/lib/types"

interface TrackCardProps {
	track: Track
	onPlay?: (track: Track) => void
	onDelete?: (trackId: string) => void
	onDownload?: (trackId: string) => void
	onShare?: (track: Track) => void
	isPlaying?: boolean
	className?: string
}

// Sub-genre accent colors — all 16 backend SubGenre values
const GENRE_COLORS: Record<string, string> = {
	afrobeats:      "bg-rose-500/10 text-rose-400 border-rose-500/20",
	afropop:        "bg-amber-500/10 text-amber-400 border-amber-500/20",
	afrofusion:     "bg-orange-500/10 text-orange-400 border-orange-500/20",
	alte:           "bg-purple-500/10 text-purple-400 border-purple-500/20",
	highlife:       "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
	amapiano_cross: "bg-green-500/10 text-green-400 border-green-500/20",
	uk_afrobeats:   "bg-blue-500/10 text-blue-400 border-blue-500/20",
	bongo_flava:    "bg-sky-500/10 text-sky-400 border-sky-500/20",
	soukous:        "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
	mbalax:         "bg-violet-500/10 text-violet-400 border-violet-500/20",
	gengetone:      "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
	benga:          "bg-teal-500/10 text-teal-400 border-teal-500/20",
	taarab:         "bg-amber-700/10 text-amber-600 border-amber-700/20",
	soca:           "bg-red-400/10 text-red-300 border-red-400/20",
	calypso:        "bg-lime-500/10 text-lime-400 border-lime-500/20",
	afro_soca:      "bg-fuchsia-500/10 text-fuchsia-400 border-fuchsia-500/20",
}

// Deterministic gradient cover art from track ID
function getCoverGradient(id: string): string {
	const gradients = [
		"from-amber-900/80 via-orange-800/50 to-yellow-900/80",
		"from-purple-900/80 via-indigo-800/50 to-violet-900/80",
		"from-green-900/80 via-teal-800/50 to-emerald-900/80",
		"from-red-900/80 via-rose-800/50 to-pink-900/80",
		"from-blue-900/80 via-indigo-800/50 to-cyan-900/80",
		"from-fuchsia-900/80 via-purple-800/50 to-pink-900/80",
		"from-teal-900/80 via-green-800/50 to-cyan-900/80",
		"from-orange-900/80 via-red-800/50 to-rose-900/80",
	]
	const hash = id.split("").reduce((a, c) => a + c.charCodeAt(0), 0)
	return gradients[hash % gradients.length] ?? "from-amber-900/80 via-orange-800/50 to-yellow-900/80"
}

export function TrackCard({
	track,
	onPlay,
	onDelete,
	onDownload,
	onShare,
	isPlaying = false,
	className,
}: TrackCardProps) {
	const [isHovered, setIsHovered] = useState(false)

	return (
		<div
			className={cn(
				"group relative rounded-xl bg-dark-bg-card border border-white/[0.06] overflow-hidden transition-all duration-300",
				"hover:border-afro-gold/20 hover:shadow-lg hover:shadow-afro-gold/5",
				className,
			)}
			onMouseEnter={() => setIsHovered(true)}
			onMouseLeave={() => setIsHovered(false)}
		>
			{/* Cover art */}
			<div
				className={cn(
					"relative aspect-square bg-gradient-to-br",
					getCoverGradient(track.id),
					"flex items-center justify-center overflow-hidden",
				)}
			>
				{/* Adire pattern overlay */}
				<div className="absolute inset-0 adire-texture opacity-30" />

				{/* Musical note icon */}
				<div
					className={cn(
						"relative z-10 w-12 h-12 rounded-full flex items-center justify-center transition-transform duration-300",
						isHovered ? "scale-90 opacity-0" : "scale-100 opacity-70",
					)}
				>
					<svg viewBox="0 0 24 24" className="w-8 h-8 fill-current text-white/60">
						<path d="M9 3v10.55A4 4 0 1 0 11 17V7h4V3H9z" />
					</svg>
				</div>

				{/* Play button overlay on hover */}
				<button
					onClick={() => onPlay?.(track)}
					className={cn(
						"absolute inset-0 flex items-center justify-center transition-all duration-300",
						isHovered ? "opacity-100" : "opacity-0",
					)}
					aria-label={isPlaying ? "Pause" : "Play"}
				>
					<div className="w-14 h-14 rounded-full bg-afro-gold flex items-center justify-center shadow-xl shadow-afro-gold/30 animate-pulse-gold">
						{isPlaying ? (
							<Pause className="w-6 h-6 text-dark-bg-primary" />
						) : (
							<Play className="w-6 h-6 text-dark-bg-primary translate-x-0.5" />
						)}
					</div>
				</button>

				{/* Playing indicator */}
				{isPlaying && !isHovered && (
					<div className="absolute bottom-2 left-2 flex gap-0.5 items-end h-5">
						{[1, 2, 3, 4].map((i) => (
							<span
								key={i}
								className="waveform-bar"
								style={{
									height: `${[60, 100, 70, 85][i - 1]}%`,
									animationDelay: `${(i - 1) * 0.15}s`,
								}}
							/>
						))}
					</div>
				)}

				{/* Duration badge */}
				<div className="absolute bottom-2 right-2 font-mono text-[10px] text-white/70 bg-black/40 px-1.5 py-0.5 rounded">
					{formatDuration(track.durationSeconds)}
				</div>
			</div>

			{/* Track info */}
			<div className="p-3">
				<div className="flex items-start justify-between gap-2">
					<div className="min-w-0">
						<h3 className="text-sm font-semibold text-zinc-100 truncate leading-tight">
							{track.title}
						</h3>
						<div className="flex items-center gap-1.5 mt-1">
							<span
								className={cn(
									"text-[10px] font-medium px-1.5 py-0.5 rounded border",
									GENRE_COLORS[track.subGenre] ?? "bg-zinc-800 text-zinc-400 border-zinc-700",
								)}
							>
								{subGenreLabel(track.subGenre)}
							</span>
							<span className="text-xs" aria-label={`Language: ${track.language}`}>
								{languageFlag(track.language)}
							</span>
						</div>
					</div>

					{/* Actions menu */}
					<DropdownMenu.Root>
						<DropdownMenu.Trigger asChild>
							<button
								className="shrink-0 w-7 h-7 rounded-md flex items-center justify-center text-zinc-500 hover:text-zinc-300 hover:bg-white/[0.06] transition-colors"
								aria-label="Track actions"
							>
								<MoreHorizontal className="w-4 h-4" />
							</button>
						</DropdownMenu.Trigger>
						<DropdownMenu.Portal>
							<DropdownMenu.Content
								className="z-50 min-w-40 rounded-lg bg-dark-bg-card border border-white/[0.08] p-1 shadow-2xl shadow-black/60 animate-slide-up"
								sideOffset={4}
								align="end"
							>
								{onDownload && (
									<DropdownMenu.Item asChild>
										<button
											onClick={() => onDownload(track.id)}
											className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs text-zinc-300 hover:text-zinc-100 hover:bg-white/[0.05] rounded-md transition-colors outline-none cursor-pointer"
										>
											<Download className="w-3.5 h-3.5" />
											Download
										</button>
									</DropdownMenu.Item>
								)}
								{onShare && (
									<DropdownMenu.Item asChild>
										<button
											onClick={() => onShare(track)}
											className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs text-zinc-300 hover:text-zinc-100 hover:bg-white/[0.05] rounded-md transition-colors outline-none cursor-pointer"
										>
											<Share2 className="w-3.5 h-3.5" />
											Share
										</button>
									</DropdownMenu.Item>
								)}
								<DropdownMenu.Separator className="my-1 border-t border-white/[0.06]" />
								{onDelete && (
									<DropdownMenu.Item asChild>
										<button
											onClick={() => onDelete(track.id)}
											className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-md transition-colors outline-none cursor-pointer"
										>
											<Trash2 className="w-3.5 h-3.5" />
											Delete
										</button>
									</DropdownMenu.Item>
								)}
							</DropdownMenu.Content>
						</DropdownMenu.Portal>
					</DropdownMenu.Root>
				</div>

				{/* Meta row */}
				<div className="flex items-center justify-between mt-2">
					<div className="flex items-center gap-1 text-[10px] text-zinc-600">
						<Headphones className="w-3 h-3" />
						<span>{formatPlayCount(track.playCount)}</span>
					</div>
					<span className="text-[10px] text-zinc-600">
						{formatRelativeDate(track.createdAt)}
					</span>
				</div>
			</div>
		</div>
	)
}
