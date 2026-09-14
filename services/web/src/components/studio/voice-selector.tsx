"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Mic2, Upload, Trash2, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"
import type { VoiceModel } from "@/lib/types"

interface VoiceSelectorProps {
	disabled?: boolean
	value: string | null
	onChange: (modelId: string | null) => void
	/** False for free/creator tiers — upload requires Pro+. */
	canClone: boolean
	onUpgradeRequired: () => void
}

const TERMINAL_VOICE_STATUSES = ["ready", "failed", "deprecated"] as const

function statusLabel(vm: VoiceModel): string {
	switch (vm.status) {
		case "ready":
			return vm.isPreset ? "Preset" : "Ready"
		case "training":
			return `Training ${vm.trainingProgressPercent}%`
		case "pending":
			return "Queued"
		case "failed":
			return "Failed"
		case "deprecated":
			return "Retired"
	}
}

export function VoiceSelector({ disabled = false, value, onChange, canClone, onUpgradeRequired }: VoiceSelectorProps) {
	const [models, setModels] = useState<VoiceModel[]>([])
	const [loading, setLoading] = useState(true)
	const [loadError, setLoadError] = useState<string | null>(null)
	const [showClone, setShowClone] = useState(false)
	const [cloneName, setCloneName] = useState("")
	const [cloneFile, setCloneFile] = useState<File | null>(null)
	const [consent, setConsent] = useState(false)
	const [uploading, setUploading] = useState(false)
	const [uploadError, setUploadError] = useState<string | null>(null)
	const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

	useEffect(() => {
		let cancelled = false
		async function load() {
			try {
				const list = await api.voices.getVoiceModels()
				if (cancelled) return
				setModels(list)
				setLoadError(null)
			} catch (err: unknown) {
				if (cancelled) return
				setLoadError(err instanceof Error ? err.message : "Could not load voices")
			} finally {
				if (!cancelled) setLoading(false)
			}
		}
		void load()
		return () => {
			cancelled = true
		}
	}, [])

	// Poll while any custom model is still training.
	useEffect(() => {
		const active = models.some((m) => !TERMINAL_VOICE_STATUSES.includes(m.status as (typeof TERMINAL_VOICE_STATUSES)[number]))
		if (!active) {
			if (pollRef.current !== null) {
				clearInterval(pollRef.current)
				pollRef.current = null
			}
			return
		}
		if (pollRef.current !== null) return
		pollRef.current = setInterval(() => {
			void (async () => {
				try {
					const list = await api.voices.getVoiceModels()
					setModels(list)
				} catch {
					// Transient — next tick retries.
				}
			})()
		}, 10_000)
		return () => {
			if (pollRef.current !== null) {
				clearInterval(pollRef.current)
				pollRef.current = null
			}
		}
	}, [models])

	const handleUpload = useCallback(async () => {
		if (!canClone) {
			onUpgradeRequired()
			return
		}
		if (!cloneName.trim() || !cloneFile || !consent || uploading) return
		setUploading(true)
		setUploadError(null)
		try {
			const vm = await api.voices.uploadVoiceModel({
				name: cloneName.trim(),
				file: cloneFile,
			})
			setModels((prev) => [...prev, vm])
			setShowClone(false)
			setCloneName("")
			setCloneFile(null)
			setConsent(false)
		} catch (err: unknown) {
			setUploadError(err instanceof Error ? err.message : "Upload failed")
		} finally {
			setUploading(false)
		}
	}, [canClone, cloneName, cloneFile, consent, uploading, onUpgradeRequired])

	const handleDelete = useCallback(
		async (id: string) => {
			try {
				await api.voices.deleteVoiceModel(id)
				setModels((prev) => prev.filter((m) => m.id !== id))
				if (value === id) onChange(null)
			} catch {
				// Best-effort — list refreshes on next mount.
			}
		},
		[value, onChange],
	)

	const presets = models.filter((m) => m.isPreset)
	const custom = models.filter((m) => !m.isPreset)
	const canSubmitClone = cloneName.trim().length > 0 && cloneFile !== null && consent && !uploading

	return (
		<div className="space-y-2">
			{loading ? (
				<p className="text-xs text-zinc-600 flex items-center gap-2">
					<Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading voices...
				</p>
			) : loadError ? (
				<p className="text-xs text-red-400">{loadError}</p>
			) : (
				<div className="flex flex-wrap gap-1.5">
					<button
						onClick={() => onChange(null)}
						disabled={disabled}
						className={cn(
							"px-3 py-1.5 rounded-full text-xs font-medium border transition-all",
							value === null
								? "border-afro-gold/50 bg-afro-gold/10 text-afro-gold"
								: "border-white/[0.07] text-zinc-500 hover:border-white/[0.14] hover:text-zinc-300",
							"disabled:opacity-50 disabled:cursor-not-allowed",
						)}
					>
						✨ AI voice
					</button>
					{[...presets, ...custom].map((vm) => {
						const usable = vm.status === "ready"
						const selected = value === vm.id
						return (
							<div
								key={vm.id}
								className={cn(
									"flex items-center gap-1 pl-3 pr-1 py-1 rounded-full text-xs font-medium border transition-all",
									selected
										? "border-afro-gold/50 bg-afro-gold/10 text-afro-gold"
										: "border-white/[0.07] text-zinc-500",
									!usable && "opacity-70",
								)}
							>
								<button
									onClick={() => usable && onChange(vm.id)}
									disabled={disabled || !usable}
									title={usable ? vm.name : `${vm.name} — ${statusLabel(vm)}`}
									className="flex items-center gap-1.5 disabled:cursor-not-allowed hover:text-zinc-200 transition-colors"
								>
									<Mic2 className="w-3 h-3" />
									{vm.name}
									{!usable && (
										<span className="text-[10px] text-zinc-600">· {statusLabel(vm)}</span>
									)}
								</button>
								{!vm.isPreset && (
									<button
										onClick={() => void handleDelete(vm.id)}
										disabled={disabled}
										aria-label={`Delete ${vm.name}`}
										className="p-1 rounded-full text-zinc-700 hover:text-red-400 transition-colors"
									>
										<Trash2 className="w-3 h-3" />
									</button>
								)}
							</div>
						)
					})}
				</div>
			)}

			{!showClone ? (
				<button
					onClick={() => {
						if (!canClone) {
							onUpgradeRequired()
							return
						}
						setShowClone(true)
					}}
					disabled={disabled}
					className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-afro-gold transition-colors disabled:opacity-50"
				>
					<Upload className="w-3.5 h-3.5" />
					Clone a voice{!canClone && <span className="text-[10px] text-afro-gold">PRO+</span>}
				</button>
			) : (
				<div className="space-y-2 rounded-lg bg-dark-bg-elevated border border-white/[0.08] p-3 animate-slide-up">
					<input
						value={cloneName}
						onChange={(e) => setCloneName(e.target.value.slice(0, 128))}
						disabled={disabled || uploading}
						placeholder="Voice name, e.g. My stage voice"
						aria-label="Voice name"
						className="w-full px-3 py-2 rounded-lg bg-dark-bg-primary border border-white/[0.08] text-sm text-zinc-100 placeholder:text-zinc-700 focus:outline-none focus:ring-1 focus:ring-afro-gold/50 disabled:opacity-50"
					/>
					<label className="flex items-center gap-2 px-3 py-2 rounded-lg bg-dark-bg-primary border border-dashed border-white/[0.12] text-xs text-zinc-400 hover:border-afro-gold/40 cursor-pointer transition-colors">
						<Upload className="w-3.5 h-3.5 shrink-0" />
						<span className="truncate">
							{cloneFile ? cloneFile.name : "Upload a clean vocal sample (MP3/WAV/FLAC/OGG)"}
						</span>
						<input
							type="file"
							accept="audio/mpeg,audio/wav,audio/flac,audio/ogg,.mp3,.wav,.flac,.ogg"
							disabled={disabled || uploading}
							onChange={(e) => setCloneFile(e.target.files?.[0] ?? null)}
							className="hidden"
						/>
					</label>
					<label className="flex items-start gap-2 text-[11px] text-zinc-500 cursor-pointer">
						<input
							type="checkbox"
							checked={consent}
							onChange={(e) => setConsent(e.target.checked)}
							disabled={disabled || uploading}
							className="mt-0.5 accent-[#D4AF37]"
						/>
						I confirm this is my own voice or I have the person&apos;s permission to clone it.
					</label>
					{uploadError && <p className="text-[10px] text-red-400">{uploadError}</p>}
					<div className="flex gap-2">
						<button
							onClick={() => void handleUpload()}
							disabled={disabled || !canSubmitClone}
							className="flex-1 py-2 rounded-lg text-xs font-semibold bg-afro-gold text-dark-bg-primary hover:bg-afro-gold-300 transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
						>
							{uploading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
							{uploading ? "Uploading..." : "Start training"}
						</button>
						<button
							onClick={() => setShowClone(false)}
							disabled={uploading}
							className="px-3 py-2 rounded-lg text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
						>
							Cancel
						</button>
					</div>
					<p className="text-[10px] text-zinc-700">
						Training takes a few hours on GPU. You&apos;ll see progress here; ready voices become selectable.
					</p>
				</div>
			)}
		</div>
	)
}
