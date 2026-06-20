"use client"

import { cn } from "@/lib/utils"
import type { JobStatus } from "@/lib/types"

interface GenerationProgressProps {
	status: JobStatus | null
	progressPercent: number
	statusMessage: string
	className?: string
}

interface Step {
	key: JobStatus
	label: string
	icon: string
}

const STEPS: Step[] = [
	{ key: "queued", label: "Queue", icon: "⏳" },
	{ key: "composing", label: "Rhythm", icon: "🥁" },
	{ key: "melodizing", label: "Melody", icon: "🎸" },
	{ key: "vocalizing", label: "Vocals", icon: "🎤" },
	{ key: "mastering", label: "Master", icon: "✨" },
	{ key: "completed", label: "Done", icon: "🎵" },
]

const STATUS_ORDER: Record<JobStatus, number> = {
	queued: 0,
	composing: 1,
	melodizing: 2,
	vocalizing: 3,
	mastering: 4,
	completed: 5,
	failed: -1,
}

export function GenerationProgress({
	status,
	progressPercent,
	statusMessage,
	className,
}: GenerationProgressProps) {
	const currentOrder = status ? (STATUS_ORDER[status] ?? -1) : -1
	const isFailed = status === "failed"
	const isComplete = status === "completed"

	return (
		<div className={cn("space-y-6", className)}>
			{/* Animated waveform visualizer */}
			<div className="flex items-end justify-center gap-1 h-16">
				{Array.from({ length: 28 }).map((_, i) => {
					const active = !isFailed && status !== null && status !== "completed"
					// Create a wave-like height pattern
					const baseHeight = 20 + Math.sin(i * 0.6) * 15 + Math.cos(i * 0.3) * 10
					return (
						<span
							key={i}
							className={cn(
								"rounded-full transition-colors duration-700",
								active ? "bg-afro-gold" : isComplete ? "bg-afro-gold/60" : "bg-zinc-700",
							)}
							style={{
								width: "3px",
								height: `${baseHeight}%`,
								animation: active ? `waveform ${0.8 + (i % 5) * 0.12}s ease-in-out infinite` : "none",
								animationDelay: `${(i * 0.06) % 1.2}s`,
								opacity: active ? 0.7 + 0.3 * (i % 3 === 0 ? 1 : 0.5) : 0.3,
							}}
						/>
					)
				})}
			</div>

			{/* Progress bar */}
			<div className="space-y-2">
				<div className="flex items-center justify-between text-xs">
					<span
						className={cn(
							"font-medium",
							isFailed ? "text-red-400" : isComplete ? "text-afro-gold" : "text-zinc-300",
						)}
					>
						{statusMessage || "Waiting..."}
					</span>
					<span className="font-mono text-zinc-500 tabular-nums">
						{isFailed ? "—" : `${Math.round(progressPercent)}%`}
					</span>
				</div>

				<div className="h-1.5 bg-dark-bg-elevated rounded-full overflow-hidden">
					<div
						className={cn(
							"h-full rounded-full transition-all duration-500 ease-out",
							isFailed
								? "bg-red-500"
								: "bg-gradient-to-r from-afro-gold-600 via-afro-gold to-amber-300",
						)}
						style={{ width: `${isFailed ? 100 : progressPercent}%` }}
					/>
				</div>
			</div>

			{/* Step indicators with inline connector */}
			<div className="relative">
				{/* Track line — sits behind circles at vertical center of the w-8 circles (top-4 = 16px) */}
				<div className="absolute top-4 left-4 right-4 h-px bg-zinc-800 pointer-events-none" />
				{/* Progress fill */}
				{!isFailed && currentOrder >= 0 && (
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
										isFailed && step.key !== "completed"
											? "border-red-500/30 bg-red-500/10 text-red-400"
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
