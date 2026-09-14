"use client"

import { cn } from "@/lib/utils"
import type { JobStatus } from "@/lib/types"

interface GenerationProgressProps {
	status: JobStatus | null
	progressPercent: number
	statusMessage: string
	estimatedSeconds?: number | null
	className?: string
}

interface Step {
	key: JobStatus
	label: string
	icon: string
}

const STEPS: Step[] = [
	{ key: "queued", label: "Queue", icon: "⏳" },
	{ key: "ml_generating", label: "Compose", icon: "🥁" },
	{ key: "audio_processing", label: "Master", icon: "✨" },
	{ key: "uploading", label: "Upload", icon: "☁️" },
	{ key: "complete", label: "Done", icon: "🎵" },
]

const STATUS_ORDER: Record<JobStatus, number> = {
	queued: 0,
	ml_generating: 1,
	audio_processing: 2,
	uploading: 3,
	complete: 4,
	failed: -1,
	cancelled: -1,
}

function formatEta(totalSeconds: number | null | undefined): string | null {
	if (totalSeconds == null || !Number.isFinite(totalSeconds) || totalSeconds <= 0) return null
	if (totalSeconds < 60) return `~${Math.round(totalSeconds)}s left`
	const mins = Math.floor(totalSeconds / 60)
	const secs = Math.round(totalSeconds % 60)
	return secs === 0 ? `~${mins}m left` : `~${mins}m ${secs}s left`
}

export function GenerationProgress({
	status,
	progressPercent,
	statusMessage,
	estimatedSeconds,
	className,
}: GenerationProgressProps) {
	const currentOrder = status ? (STATUS_ORDER[status] ?? -1) : -1
	const isFailed = status === "failed"
	const isCancelled = status === "cancelled"
	const isComplete = status === "complete"
	const isActive = !isFailed && !isCancelled && status !== null && !isComplete
	const clamped = Math.max(0, Math.min(100, Math.round(progressPercent)))
	const eta = isActive ? formatEta(estimatedSeconds) : null

	return (
		<div className={cn("space-y-6", className)}>
			{/* Animated waveform visualizer */}
			<div className="flex items-end justify-center gap-1 h-16" aria-hidden="true">
				{Array.from({ length: 28 }).map((_, i) => {
					const baseHeight = 20 + Math.sin(i * 0.6) * 15 + Math.cos(i * 0.3) * 10
					return (
						<span
							key={i}
							className={cn(
								"rounded-full transition-colors duration-700",
								isActive ? "bg-afro-gold" : isComplete ? "bg-afro-gold/60" : "bg-zinc-700",
							)}
							style={{
								width: "3px",
								height: `${baseHeight}%`,
								animation: isActive ? `waveform ${0.8 + (i % 5) * 0.12}s ease-in-out infinite` : "none",
								animationDelay: `${(i * 0.06) % 1.2}s`,
								opacity: isActive ? 0.7 + 0.3 * (i % 3 === 0 ? 1 : 0.5) : 0.3,
							}}
						/>
					)
				})}
			</div>

			{/* Progress bar */}
			<div className="space-y-2">
				<div className="flex items-center justify-between text-xs gap-3">
					<span
						className={cn(
							"font-medium truncate",
							isFailed ? "text-red-400" : isCancelled ? "text-zinc-400" : isComplete ? "text-afro-gold" : "text-zinc-300",
						)}
					>
						{statusMessage || "Waiting..."}
					</span>
					<span className="font-mono text-zinc-500 tabular-nums shrink-0">
						{isFailed || isCancelled ? "—" : `${clamped}%`}
						{eta ? ` · ${eta}` : ""}
					</span>
				</div>

				<div
					className="h-1.5 bg-dark-bg-elevated rounded-full overflow-hidden"
					role="progressbar"
					aria-valuemin={0}
					aria-valuemax={100}
					aria-valuenow={clamped}
					aria-label={statusMessage || "Generation progress"}
				>
					<div
						className={cn(
							"h-full rounded-full transition-all duration-500 ease-out",
							isFailed
								? "bg-red-500"
								: isCancelled
									? "bg-zinc-600"
									: "bg-gradient-to-r from-afro-gold-600 via-afro-gold to-amber-300",
						)}
						style={{ width: `${isFailed || isCancelled ? 100 : clamped}%` }}
					/>
				</div>
			</div>

			{/* Step indicators with inline connector */}
			<div className="relative">
				{/* Track line — sits behind circles at vertical center of the w-8 circles (top-4 = 16px) */}
				<div className="absolute top-4 left-4 right-4 h-px bg-zinc-800 pointer-events-none" />
				{/* Progress fill */}
				{!isFailed && !isCancelled && currentOrder >= 0 && (
					<div
						className="absolute top-4 left-4 h-px bg-gradient-to-r from-afro-gold-600 to-afro-gold transition-all duration-700 pointer-events-none"
						style={{
							width: `calc(${Math.min(currentOrder / (STEPS.length - 1), 1)} * (100% - 2rem))`,
						}}
					/>
				)}

				<div className="relative flex items-start justify-between">
					{STEPS.map((step) => {
						const stepOrder = STATUS_ORDER[step.key]
						const isDone = currentOrder > stepOrder
						const isCurrent = currentOrder === stepOrder
						const isPending = currentOrder < stepOrder

						return (
							<div key={step.key} className="relative z-10 flex flex-col items-center gap-1 flex-1">
								{/* Step circle */}
								<div
									className={cn(
										"w-8 h-8 rounded-full border flex items-center justify-center text-sm transition-all duration-500",
										isFailed
											? "border-red-500/30 bg-red-500/10 text-red-400"
											: isCancelled
												? "border-zinc-700 bg-zinc-800/50 text-zinc-500"
												: isDone
													? "border-afro-gold/50 bg-afro-gold/15 text-afro-gold"
													: isCurrent
														? "border-afro-gold bg-afro-gold/20 text-afro-gold animate-pulse"
														: "border-zinc-800 bg-dark-bg-elevated text-zinc-700",
									)}
								>
									{isDone ? "✓" : step.icon}
								</div>

								{/* Step label */}
								<span
									className={cn(
										"text-[9px] font-medium uppercase tracking-wider transition-colors duration-500",
										isFailed
											? "text-zinc-700"
											: isCancelled
												? "text-zinc-600"
												: isDone || isCurrent
													? "text-afro-gold/70"
													: isPending
														? "text-zinc-800"
														: "text-zinc-700",
									)}
								>
									{step.label}
								</span>
							</div>
						)
					})}
				</div>
			</div>
		</div>
	)
}
