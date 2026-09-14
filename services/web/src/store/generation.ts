"use client"

import { create } from "zustand"
import { api } from "@/lib/api"
import type { GenerationRequest, GenerationJob, Rendition, Track, JobStatus } from "@/lib/types"

export const MAX_RENDITIONS = 3

export function randomSeed(): number {
	return Math.floor(Math.random() * 2 ** 31)
}

interface GenerationState {
	currentJobId: string | null
	currentTrackId: string | null
	jobStatus: JobStatus | null
	progressPercent: number
	statusMessage: string
	estimatedSeconds: number | null
	currentTrack: Track | null
	isGenerating: boolean
	error: string | null
	pollIntervalId: ReturnType<typeof setInterval> | null
	// Multi-rendition state — each rendition is its own backend job (1 credit each)
	renditions: Rendition[]
	isGeneratingRenditions: boolean
	activeRenditionJobId: string | null
	renditionPollIntervalId: ReturnType<typeof setInterval> | null

	// Actions
	submitGeneration: (req: GenerationRequest) => Promise<void>
	pollJobStatus: (jobId: string) => void
	stopPolling: () => void
	cancelGeneration: () => Promise<void>
	reset: () => void
	submitRenditions: (req: GenerationRequest, count: number) => Promise<void>
	selectRendition: (jobId: string) => void
	cancelRenditions: () => Promise<void>
}

const STATUS_MESSAGES: Record<JobStatus, string> = {
	queued: "Your track is queued...",
	ml_generating: "Composing your track...",
	audio_processing: "Mastering your track...",
	uploading: "Uploading your track...",
	complete: "Your track is ready!",
	failed: "Generation failed. Please try again.",
	cancelled: "Generation cancelled.",
}

const TERMINAL_STATUSES: JobStatus[] = ["complete", "failed", "cancelled"]

export const useGenerationStore = create<GenerationState>((set, get) => ({
	currentJobId: null,
	currentTrackId: null,
	jobStatus: null,
	progressPercent: 0,
	statusMessage: "",
	estimatedSeconds: null,
	currentTrack: null,
	isGenerating: false,
	error: null,
	pollIntervalId: null,
	renditions: [],
	isGeneratingRenditions: false,
	activeRenditionJobId: null,
	renditionPollIntervalId: null,

	async submitGeneration(req) {
		const { stopPolling } = get()
		stopPolling()

		set({
			isGenerating: true,
			error: null,
			currentTrack: null,
			currentTrackId: null,
			currentJobId: null,
			progressPercent: 0,
			jobStatus: "queued",
			statusMessage: STATUS_MESSAGES.queued,
			estimatedSeconds: null,
		})

		try {
			const res = await api.tracks.generateTrack(req)
			set({ currentJobId: res.id, estimatedSeconds: res.estimatedSeconds ?? null })
			get().pollJobStatus(res.id)
		} catch (err: unknown) {
			const message = err instanceof Error ? err.message : "Generation failed"
			set({
				isGenerating: false,
				error: message,
				jobStatus: "failed",
				statusMessage: STATUS_MESSAGES.failed,
			})
		}
	},

	pollJobStatus(jobId) {
		const { stopPolling } = get()
		stopPolling()

		let consecutiveFailures = 0
		let settled = false

		const handleJob = async (job: GenerationJob) => {
			if (settled) return
			consecutiveFailures = 0

			// Ignore stale polls from a previous job (e.g. user resubmitted).
			if (get().currentJobId !== jobId) return

			set({
				jobStatus: job.status,
				progressPercent: job.progressPercent,
				currentTrackId: job.trackId ?? get().currentTrackId,
				statusMessage:
					STATUS_MESSAGES[job.status] ??
					job.errorMessage ??
					STATUS_MESSAGES.queued,
			})

			if (TERMINAL_STATUSES.includes(job.status)) {
				settled = true
				get().stopPolling()

				if (job.status === "complete") {
					try {
						const { currentTrackId } = get()
						if (currentTrackId) {
							const track = await api.tracks.getTrack(currentTrackId)
							set({ currentTrack: track, isGenerating: false })
						} else {
							set({ isGenerating: false })
						}
					} catch {
						set({ isGenerating: false })
					}
				} else if (job.status === "cancelled") {
					set({ isGenerating: false })
				} else {
					set({
						isGenerating: false,
						error: job.errorMessage ?? "Generation failed",
					})
				}
			}
		}

		// Fetch immediately so the UI reacts without waiting one interval tick.
		api.tracks.getJobStatus(jobId).then(handleJob).catch(() => {})

		const intervalId = setInterval(async () => {
			try {
				const job: GenerationJob = await api.tracks.getJobStatus(jobId)
				await handleJob(job)
			} catch (err: unknown) {
				consecutiveFailures += 1
				// Transient network errors: tolerate up to 5 (~10 s) before giving up —
				// the job keeps running server-side regardless of poll failures.
				if (consecutiveFailures >= 5) {
					const message = err instanceof Error ? err.message : "Polling failed"
					set({
						isGenerating: false,
						error: message,
						jobStatus: "failed",
						statusMessage: STATUS_MESSAGES.failed,
					})
					get().stopPolling()
				}
			}
		}, 2_000)

		set({ pollIntervalId: intervalId })
	},

	stopPolling() {
		const { pollIntervalId } = get()
		if (pollIntervalId !== null) {
			clearInterval(pollIntervalId)
			set({ pollIntervalId: null })
		}
	},

	async cancelGeneration() {
		const { currentJobId, stopPolling } = get()
		stopPolling()
		if (currentJobId) {
			try {
				await api.tracks.cancelGeneration(currentJobId)
			} catch {
				// Job may have already completed between click and call — ignore.
			}
		}
		set({
			currentJobId: null,
			currentTrackId: null,
			jobStatus: "cancelled",
			progressPercent: 0,
			statusMessage: STATUS_MESSAGES.cancelled,
			estimatedSeconds: null,
			isGenerating: false,
			error: null,
		})
	},

	reset() {
		get().stopPolling()
		const { renditionPollIntervalId } = get()
		if (renditionPollIntervalId !== null) {
			clearInterval(renditionPollIntervalId)
		}
		set({
			currentJobId: null,
			currentTrackId: null,
			jobStatus: null,
			progressPercent: 0,
			statusMessage: "",
			estimatedSeconds: null,
			currentTrack: null,
			isGenerating: false,
			error: null,
			pollIntervalId: null,
			renditions: [],
			isGeneratingRenditions: false,
			activeRenditionJobId: null,
			renditionPollIntervalId: null,
		})
	},

	async submitRenditions(req, count) {
		const clamped = Math.max(2, Math.min(MAX_RENDITIONS, Math.floor(count)))
		get().stopPolling()
		const { renditionPollIntervalId } = get()
		if (renditionPollIntervalId !== null) {
			clearInterval(renditionPollIntervalId)
			set({ renditionPollIntervalId: null })
		}

		set({
			isGeneratingRenditions: true,
			isGenerating: true,
			error: null,
			currentTrack: null,
			currentTrackId: null,
			currentJobId: null,
			jobStatus: "queued",
			progressPercent: 0,
			statusMessage: `Starting ${clamped} renditions — ${clamped} credits will be used...`,
			renditions: [],
			activeRenditionJobId: null,
		})

		// Distinct explicit seeds per rendition so outputs actually differ
		// (YuE2 defaults to seed 0, which would otherwise repeat the same take).
		const seeds = new Set<number>()
		while (seeds.size < clamped) {
			seeds.add(randomSeed())
		}

		const started: Rendition[] = []
		let submitError: string | null = null
		for (const seed of seeds) {
			try {
				const res = await api.tracks.generateTrack({ ...req, seed })
				started.push({
					jobId: res.id,
					seed,
					status: "queued",
					progressPercent: 0,
					statusMessage: STATUS_MESSAGES.queued,
					trackId: null,
					track: null,
					error: null,
				})
				set({ renditions: [...started] })
			} catch (err: unknown) {
				// Most likely quota exhausted mid-batch — keep what started.
				submitError = err instanceof Error ? err.message : "Failed to start a rendition"
				break
			}
		}

		if (started.length === 0) {
			set({
				isGeneratingRenditions: false,
				isGenerating: false,
				error: submitError ?? "Failed to start renditions",
				jobStatus: "failed",
				statusMessage: STATUS_MESSAGES.failed,
			})
			return
		}

		if (submitError !== null) {
			set({
				error: `Only ${started.length} of ${clamped} renditions started: ${submitError}`,
			})
		}

		let consecutiveFailures = 0
		const intervalId = setInterval(async () => {
			const { renditions } = get()
			const pending = renditions.filter(
				(r) => r.status !== null && !TERMINAL_STATUSES.includes(r.status),
			)
			if (pending.length === 0) {
				const { renditionPollIntervalId: id } = get()
				if (id !== null) {
					clearInterval(id)
					set({ renditionPollIntervalId: null })
				}
				return
			}

			try {
				const updates = await Promise.all(
					pending.map(async (r) => {
						const job: GenerationJob = await api.tracks.getJobStatus(r.jobId)
						let track: Track | null = r.track
						let error: string | null = null
						if (job.status === "complete" && job.trackId && track === null) {
							try {
								track = await api.tracks.getTrack(job.trackId)
							} catch {
								// Track read is best-effort; job is still complete.
							}
						}
						if (job.status === "failed") {
							error = job.errorMessage ?? "Generation failed"
						}
						return {
							...r,
							status: job.status,
							progressPercent: job.progressPercent,
							statusMessage: STATUS_MESSAGES[job.status] ?? job.errorMessage ?? STATUS_MESSAGES.queued,
							trackId: job.trackId ?? r.trackId,
							track,
							error,
						}
					}),
				)
				consecutiveFailures = 0

				const merged = get().renditions.map(
					(r) => updates.find((u) => u.jobId === r.jobId) ?? r,
				)
				const done = merged.filter((r) => r.status === "complete" && r.track !== null)
				const failed = merged.filter((r) => r.status === "failed").length
				const update: Partial<GenerationState> = { renditions: merged }
				const firstDone = done[0]

				if (done.length > 0 && get().currentTrack === null && firstDone?.track) {
					update.currentTrack = firstDone.track
					update.currentTrackId = firstDone.trackId
					update.activeRenditionJobId = firstDone.jobId
				}
				const total = merged.length
				const finishedCount = merged.filter((r) =>
					r.status !== null && TERMINAL_STATUSES.includes(r.status),
				).length
				if (finishedCount === total) {
					update.isGeneratingRenditions = false
					update.isGenerating = false
					update.jobStatus = failed === total ? "failed" : "complete"
					update.progressPercent = 100
					update.statusMessage =
						failed === total
							? "All renditions failed. Please try again."
							: `${done.length} of ${total} renditions ready — pick your favourite.`
				} else {
					update.progressPercent = Math.round(
						merged.reduce((acc, r) => acc + r.progressPercent, 0) / Math.max(total, 1),
					)
					update.statusMessage = `Composing rendition ${finishedCount + 1} of ${total}...`
				}
				set(update)
			} catch {
				consecutiveFailures += 1
				if (consecutiveFailures >= 5) {
					const { renditionPollIntervalId: id } = get()
					if (id !== null) {
						clearInterval(id)
						set({ renditionPollIntervalId: null })
					}
					set({
						isGeneratingRenditions: false,
						isGenerating: false,
						error: "Lost contact with the server while polling renditions",
						jobStatus: "failed",
						statusMessage: STATUS_MESSAGES.failed,
					})
				}
			}
		}, 2_000)

		set({ renditionPollIntervalId: intervalId })
	},

	selectRendition(jobId) {
		const r = get().renditions.find((x) => x.jobId === jobId)
		if (r?.track) {
			set({
				activeRenditionJobId: jobId,
				currentTrack: r.track,
				currentTrackId: r.trackId,
			})
		}
	},

	async cancelRenditions() {
		const { renditionPollIntervalId, renditions } = get()
		if (renditionPollIntervalId !== null) {
			clearInterval(renditionPollIntervalId)
			set({ renditionPollIntervalId: null })
		}
		for (const r of renditions) {
			if (r.status !== null && !TERMINAL_STATUSES.includes(r.status)) {
				try {
					await api.tracks.cancelGeneration(r.jobId)
				} catch {
					// Already finished between click and call — ignore.
				}
			}
		}
		set({
			renditions: [],
			isGeneratingRenditions: false,
			activeRenditionJobId: null,
			isGenerating: false,
			jobStatus: "cancelled",
			progressPercent: 0,
			statusMessage: STATUS_MESSAGES.cancelled,
			error: null,
		})
	},
}))