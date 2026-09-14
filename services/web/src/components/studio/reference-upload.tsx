"use client"

import { useCallback, useState } from "react"
import { Disc3, Loader2, Upload, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"

interface ReferenceUploadProps {
	disabled?: boolean
	referenceKey: string | null
	fileName: string | null
	onAttached: (key: string, fileName: string) => void
	onCleared: () => void
}

function SectionLabel({ children }: { children: React.ReactNode }) {
	return (
		<span className="text-[10px] font-mono uppercase tracking-widest text-zinc-600">
			{children}
		</span>
	)
}

export function ReferenceUpload({
	disabled = false,
	referenceKey,
	fileName,
	onAttached,
	onCleared,
}: ReferenceUploadProps) {
	const [uploading, setUploading] = useState(false)
	const [error, setError] = useState<string | null>(null)

	const handleFile = useCallback(
		async (file: File | null) => {
			if (!file || uploading) return
			setUploading(true)
			setError(null)
			try {
				const { key } = await api.tracks.uploadReference(file)
				onAttached(key, file.name)
			} catch (err: unknown) {
				setError(err instanceof Error ? err.message : "Reference upload failed")
			} finally {
				setUploading(false)
			}
		},
		[uploading, onAttached],
	)

	return (
		<div className="space-y-2">
			<SectionLabel>Starting point</SectionLabel>
			{referenceKey && fileName ? (
				<div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-afro-gold/10 border border-afro-gold/30">
					<Disc3 className="w-4 h-4 text-afro-gold shrink-0" />
					<div className="flex-1 min-w-0">
						<p className="text-xs text-zinc-200 truncate">{fileName}</p>
						<p className="text-[10px] text-zinc-500">
							Tempo, key &amp; feel will be auto-detected from this track.
						</p>
					</div>
					<button
						onClick={onCleared}
						disabled={disabled}
						aria-label="Remove reference track"
						className="p-1 rounded-full text-zinc-500 hover:text-red-400 transition-colors disabled:opacity-50"
					>
						<X className="w-3.5 h-3.5" />
					</button>
				</div>
			) : (
				<label
					className={cn(
						"flex items-center gap-2 px-3 py-2.5 rounded-lg border border-dashed border-white/[0.12] text-xs text-zinc-500 hover:border-afro-gold/40 hover:text-zinc-300 cursor-pointer transition-colors",
						(disabled || uploading) && "opacity-60 pointer-events-none",
					)}
				>
					{uploading ? (
						<Loader2 className="w-4 h-4 shrink-0 animate-spin text-afro-gold" />
					) : (
						<Upload className="w-4 h-4 shrink-0" />
					)}
					<span className="truncate">
						{uploading ? "Uploading reference..." : "Use a beat or song as a starting point (MP3/WAV/FLAC/OGG)"}
					</span>
					<input
						type="file"
						accept="audio/mpeg,audio/wav,audio/flac,audio/ogg,.mp3,.wav,.flac,.ogg"
						disabled={disabled || uploading}
						onChange={(e) => void handleFile(e.target.files?.[0] ?? null)}
						className="hidden"
					/>
				</label>
			)}
			{error && <p className="text-[10px] text-red-400">{error}</p>}
		</div>
	)
}
