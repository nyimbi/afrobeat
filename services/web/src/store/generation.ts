"use client"

import { create } from "zustand"
import { api } from "@/lib/api"
import type { GenerationRequest, GenerationJob, Track, JobStatus } from "@/lib/types"

interface GenerationState {
	currentJobId: string | null
	currentTrackId: string | null
	jobStatus: JobStatus | null
	progressPercent: number
	statusMessage: string
	currentTrack: Track | null
	isGenerating: boolean
	error: string | null
	pollIntervalId: ReturnType<typeof setInterval> | null

	// Actions
	submitGeneration: (req: GenerationRequest) => Promise<void>
	pollJobStatus: (jobId: string) => void
	stopPolling: () => void
	cancelGeneration: () => void
	reset: () => void
}

const STATUS_MESSAGES: Record<JobStatus, string> = {
	queued: "Your track is queued...",
	composing: "Composing the rhythm...",
	melodizing: "Weaving the melody...",
	vocalizing: "Adding the vocals...",
	mastering: "Mastering your track...",
	completed: "Your track is ready!",
	failed: "Generation failed. Please try again.",
}

const TERMINAL_STATUSES: JobStatus[] = ["completed", "failed"]

export const useGenerationStore = create<GenerationState>((set, get) => ({
	currentJobId: null,
	currentTrackId: null,
	jobStatus: null,
	progressPercent: 0,
	statusMessage: "",
	currentTrack: null,
	isGenerating: false,
	error: null,
	pollIntervalId: null,

	async submitGeneration(req) {
		const { stopPolling } = get()
		stopPolling()

		set({
			isGenerating: true,
			error: null,
			currentTrack: null,
			progressPercent: 0,
			jobStatus: "queued",
			statusMessage: STATUS_MESSAGES.queued,
		})

		try {
			const res = await api.tracks.generateTrack(req)
			set({
				currentJobId: res.jobId,
				currentTrackId: res.trackId,
			})
			get().pollJobStatus(res.jobId)
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

		const intervalId = setInterval(async () => {
			try {
				const job: GenerationJob = await api.tracks.getJobStatus(jobId)

				set({
					jobStatus: job.status,
					progressPercent: job.progressPercent,
					statusMessage: STATUS_MESSAGES[job.status] ?? job.statusMessage,
				})

				if (TERMINAL_STATUSES.includes(job.status)) {
					get().stopPolling()

					if (job.status === "completed") {
						try {
							const { currentTrackId } = get()
							if (currentTrackId) {
								const track = await api.tracks.getTrack(currentTrackId)
								set({ currentTrack: track, isGenerating: false })
							}
						} catch {
							set({ isGenerating: false })
						}
					} else {
						set({
							isGenerating: false,
							error: job.errorMessage ?? "Generation failed",
						})
					}
				}
			} catch (err: unknown) {
				const message = err instanceof Error ? err.message : "Polling failed"
				set({
					isGenerating: false,
					error: message,
					jobStatus: "failed",
					statusMessage: STATUS_MESSAGES.failed,
				})
				get().stopPolling()
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

	cancelGeneration() {
		get().stopPolling()
		set({
			currentJobId: null,
			currentTrackId: null,
			jobStatus: null,
			progressPercent: 0,
			statusMessage: "",
			isGenerating: false,
			error: null,
		})
	},

	reset() {
		get().stopPolling()
		set({
			currentJobId: null,
			currentTrackId: null,
			jobStatus: null,
			progressPercent: 0,
			statusMessage: "",
			currentTrack: null,
			isGenerating: false,
			error: null,
			pollIntervalId: null,
		})
	},
}))
