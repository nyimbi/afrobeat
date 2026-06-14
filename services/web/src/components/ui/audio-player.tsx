"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { Play, Pause, Volume2, VolumeX } from "lucide-react"
import { cn, formatDuration } from "@/lib/utils"

interface AudioPlayerProps {
	src: string
	onEnded?: () => void
	showWaveform?: boolean
	mini?: boolean
	className?: string
}

// Use a loose interface so we aren't fighting WaveSurfer's exact generic types
interface WSInstance {
	destroy: () => void
	play: () => void
	pause: () => void
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	on: (event: any, cb: (...args: any[]) => void) => void
	getDuration: () => number
	getCurrentTime: () => number
	setVolume: (v: number) => void
	setMuted: (m: boolean) => void
	isPlaying: () => boolean
}

export function AudioPlayer({
	src,
	onEnded,
	showWaveform = true,
	mini = false,
	className,
}: AudioPlayerProps) {
	const containerRef = useRef<HTMLDivElement>(null)
	const wsRef = useRef<WSInstance | null>(null)
	const [isPlaying, setIsPlaying] = useState(false)
	const [isReady, setIsReady] = useState(false)
	const [currentTime, setCurrentTime] = useState(0)
	const [duration, setDuration] = useState(0)
	const [volume, setVolume] = useState(0.8)
	const [isMuted, setIsMuted] = useState(false)
	const [isLoading, setIsLoading] = useState(true)

	useEffect(() => {
		if (!containerRef.current || !src) return

		let destroyed = false

		const init = async () => {
			const WaveSurfer = (await import("wavesurfer.js")).default
			if (destroyed || !containerRef.current) return

			const ws = WaveSurfer.create({
				container: containerRef.current,
				waveColor: "rgba(212, 175, 55, 0.25)",
				progressColor: "#D4AF37",
				cursorColor: "rgba(212, 175, 55, 0.8)",
				cursorWidth: 2,
				barWidth: 2,
				barGap: 1,
				barRadius: 2,
				height: mini ? 32 : 64,
				normalize: true,
				url: src,
			}) as unknown as WSInstance

			wsRef.current = ws

			ws.on("ready", () => {
				if (destroyed) return
				setIsReady(true)
				setIsLoading(false)
				setDuration(ws.getDuration())
				ws.setVolume(volume)
			})

			ws.on("audioprocess", () => {
				if (destroyed) return
				setCurrentTime(ws.getCurrentTime())
			})

			ws.on("play", () => { if (!destroyed) setIsPlaying(true) })
			ws.on("pause", () => { if (!destroyed) setIsPlaying(false) })
			ws.on("finish", () => {
				if (destroyed) return
				setIsPlaying(false)
				setCurrentTime(0)
				onEnded?.()
			})

			ws.on("loading", () => { if (!destroyed) setIsLoading(true) })
		}

		init().catch(console.error)

		return () => {
			destroyed = true
			wsRef.current?.destroy()
			wsRef.current = null
		}
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [src])

	const togglePlay = useCallback(() => {
		const ws = wsRef.current
		if (!ws || !isReady) return
		if (isPlaying) ws.pause()
		else ws.play()
	}, [isPlaying, isReady])

	const toggleMute = useCallback(() => {
		const ws = wsRef.current
		if (!ws) return
		const next = !isMuted
		ws.setMuted(next)
		setIsMuted(next)
	}, [isMuted])

	const handleVolumeChange = useCallback(
		(e: React.ChangeEvent<HTMLInputElement>) => {
			const v = parseFloat(e.target.value)
			const ws = wsRef.current
			if (!ws) return
			ws.setVolume(v)
			setVolume(v)
			if (v === 0) setIsMuted(true)
			else if (isMuted) {
				setIsMuted(false)
			}
		},
		[isMuted],
	)

	if (mini) {
		return (
			<div className={cn("flex items-center gap-3", className)}>
				<button
					onClick={togglePlay}
					disabled={!isReady}
					className="w-8 h-8 rounded-full bg-afro-gold/10 border border-afro-gold/30 flex items-center justify-center text-afro-gold hover:bg-afro-gold/20 transition-colors disabled:opacity-40"
				>
					{isPlaying ? (
						<Pause className="w-3.5 h-3.5" />
					) : (
						<Play className="w-3.5 h-3.5 translate-x-px" />
					)}
				</button>
				<div
					ref={containerRef}
					className={cn("flex-1 min-w-0", isLoading && "opacity-0")}
				/>
				<span className="font-mono text-xs text-zinc-500 shrink-0 tabular-nums">
					{formatDuration(currentTime)}/{formatDuration(duration)}
				</span>
			</div>
		)
	}

	return (
		<div className={cn("space-y-3", className)}>
			{showWaveform && (
				<div className="relative">
					{isLoading && (
						<div className="absolute inset-0 flex items-center justify-center gap-0.5">
							{Array.from({ length: 40 }).map((_, i) => (
								<span
									key={i}
									className="waveform-bar h-12"
									style={{ animationDelay: `${(i * 0.04) % 1.2}s` }}
								/>
							))}
						</div>
					)}
					<div
						ref={containerRef}
						className={cn("w-full transition-opacity", isLoading ? "opacity-0" : "opacity-100")}
					/>
				</div>
			)}

			<div className="flex items-center gap-4">
				<button
					onClick={togglePlay}
					disabled={!isReady}
					className="w-10 h-10 rounded-full bg-afro-gold flex items-center justify-center text-dark-bg-primary hover:bg-afro-gold-300 transition-colors disabled:opacity-40 shrink-0"
					aria-label={isPlaying ? "Pause" : "Play"}
				>
					{isPlaying ? (
						<Pause className="w-4 h-4" />
					) : (
						<Play className="w-4 h-4 translate-x-px" />
					)}
				</button>

				<div className="font-mono text-xs text-zinc-400 shrink-0 tabular-nums">
					{formatDuration(currentTime)}
					<span className="text-zinc-600"> / </span>
					{formatDuration(duration)}
				</div>

				<div className="flex-1" />

				<div className="flex items-center gap-2">
					<button
						onClick={toggleMute}
						className="text-zinc-500 hover:text-zinc-300 transition-colors"
						aria-label={isMuted ? "Unmute" : "Mute"}
					>
						{isMuted || volume === 0 ? (
							<VolumeX className="w-4 h-4" />
						) : (
							<Volume2 className="w-4 h-4" />
						)}
					</button>
					<input
						type="range"
						min={0}
						max={1}
						step={0.01}
						value={isMuted ? 0 : volume}
						onChange={handleVolumeChange}
						className="w-20 h-1 accent-afro-gold cursor-pointer"
						aria-label="Volume"
					/>
				</div>
			</div>
		</div>
	)
}
