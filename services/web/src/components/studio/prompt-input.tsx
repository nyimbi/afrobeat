"use client"

import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"

const PLACEHOLDERS = [
	"Late night Lagos, romantic afropop vibes...",
	"High energy Detty December anthem, full of life...",
	"Melancholic alte love song, reminiscing and real...",
	"Amapiano sunrise, slow jam with log drum energy...",
	"UK afrobeats banger, trap influenced, club-ready...",
	"Afrofusion introspective, jùjú roots meets modern production...",
	"Yoruba praise song, spiritual and uplifting...",
	"Pidgin street anthem, hustler story, real talk...",
]

const MOOD_CHIPS = [
	{ label: "Romantic", emoji: "💕" },
	{ label: "Party", emoji: "🎉" },
	{ label: "Melancholic", emoji: "🌧️" },
	{ label: "Motivational", emoji: "💪" },
	{ label: "Spiritual", emoji: "🙏" },
	{ label: "Nostalgic", emoji: "🌅" },
]

const MAX_CHARS = 500

interface PromptInputProps {
	value: string
	onChange: (value: string) => void
	disabled?: boolean
	className?: string
}

export function PromptInput({ value, onChange, disabled, className }: PromptInputProps) {
	const [placeholderIdx, setPlaceholderIdx] = useState(0)
	const [isFocused, setIsFocused] = useState(false)
	const textareaRef = useRef<HTMLTextAreaElement>(null)

	// Rotate placeholder every 4s when not focused and empty
	useEffect(() => {
		if (isFocused || value) return
		const id = setInterval(() => {
			setPlaceholderIdx((i) => (i + 1) % PLACEHOLDERS.length)
		}, 4_000)
		return () => clearInterval(id)
	}, [isFocused, value])

	// Auto-grow textarea
	useEffect(() => {
		const el = textareaRef.current
		if (!el) return
		el.style.height = "auto"
		el.style.height = `${Math.min(el.scrollHeight, 200)}px`
	}, [value])

	function handleChip(chip: string) {
		const separator = value.trimEnd() ? (value.endsWith(",") ? " " : ", ") : ""
		const next = (value.trimEnd() + separator + chip.toLowerCase() + " vibes").slice(0, MAX_CHARS)
		onChange(next)
		textareaRef.current?.focus()
	}

	const remaining = MAX_CHARS - value.length
	const isNearLimit = remaining < 80
	const isAtLimit = remaining <= 0

	return (
		<div className={cn("space-y-3", className)}>
			{/* Textarea */}
			<div
				className={cn(
					"relative rounded-xl border transition-all duration-200",
					isFocused
						? "border-afro-gold/50 shadow-gold"
						: "border-white/[0.08] hover:border-white/[0.14]",
					disabled && "opacity-50 pointer-events-none",
				)}
			>
				<textarea
					ref={textareaRef}
					value={value}
					onChange={(e) => {
						if (e.target.value.length <= MAX_CHARS) onChange(e.target.value)
					}}
					onFocus={() => setIsFocused(true)}
					onBlur={() => setIsFocused(false)}
					disabled={disabled}
					placeholder={PLACEHOLDERS[placeholderIdx]}
					rows={3}
					className="w-full resize-none bg-transparent px-4 pt-4 pb-8 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none font-sans leading-relaxed"
					style={{ minHeight: "96px" }}
					aria-label="Describe your vibe"
				/>

				{/* Character counter */}
				<div className="absolute bottom-2 right-3 flex items-center gap-2">
					<span
						className={cn(
							"font-mono text-[10px] tabular-nums transition-colors",
							isAtLimit
								? "text-red-400"
								: isNearLimit
									? "text-amber-400"
									: "text-zinc-700",
						)}
					>
						{remaining}
					</span>
				</div>
			</div>

			{/* Mood chips */}
			<div className="flex flex-wrap gap-1.5">
				{MOOD_CHIPS.map(({ label, emoji }) => (
					<button
						key={label}
						type="button"
						onClick={() => handleChip(label)}
						disabled={disabled}
						className={cn(
							"flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium",
							"bg-dark-bg-elevated border border-white/[0.08] text-zinc-400",
							"hover:border-afro-gold/30 hover:text-afro-gold hover:bg-afro-gold/5",
							"transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed",
						)}
					>
						<span role="img" aria-label={label}>{emoji}</span>
						{label}
					</button>
				))}
			</div>
		</div>
	)
}
