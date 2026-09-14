import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useGenerationStore } from "../generation"
import { api } from "@/lib/api"
import type { GenerationJob, GenerationRequest, GenerationResponse, Track } from "@/lib/types"

vi.mock("@/lib/api", () => ({
	api: {
		tracks: {
			generateTrack: vi.fn(),
			getJobStatus: vi.fn(),
			getTrack: vi.fn(),
			cancelGeneration: vi.fn(),
		},
	},
}))

const tracks = vi.mocked(api.tracks)

function req(overrides: Partial<GenerationRequest> = {}): GenerationRequest {
	return {
		prompt: "lagos night drive",
		subGenre: "afropop",
		language: "english",
		energyLevel: 6,
		durationSeconds: 60,
		bpm: null,
		voiceModelId: null,
		lyrics: null,
		seed: null,
		referenceAudioKey: null,
		...overrides,
	}
}

function job(overrides: Partial<GenerationJob> = {}): GenerationJob {
	return {
		id: "job-1",
		status: "queued",
		progressPercent: 0,
		promptUsed: "lagos night drive",
		modelUsed: null,
		errorMessage: null,
		trackId: null,
		createdAt: "",
		startedAt: null,
		completedAt: null,
		...overrides,
	}
}

function track(id: string): Track {
	return {
		id,
		userId: "user-1",
		title: `Track ${id}`,
		subGenre: "afropop",
		language: "english",
		prompt: "lagos night drive",
		durationSeconds: 60,
		bpm: 100,
		musicalKey: null,
		audioUrl: `https://cdn.example/${id}.mp3`,
		previewUrl: null,
		coverArtUrl: null,
		status: "ready",
		playCount: 0,
		createdAt: "",
		updatedAt: "",
	}
}

function submitResponse(id: string): GenerationResponse {
	return { id, status: "queued", progressPercent: 0, statusMessage: "", estimatedSeconds: 90 }
}

beforeEach(() => {
	vi.clearAllMocks()
	vi.useFakeTimers()
	useGenerationStore.getState().reset()
})

afterEach(() => {
	useGenerationStore.getState().reset()
	vi.useRealTimers()
})

describe("submitGeneration", () => {
	it("submits, polls, and stores the finished track", async () => {
		tracks.generateTrack.mockResolvedValueOnce(submitResponse("job-1"))
		tracks.getJobStatus.mockResolvedValue(job({ id: "job-1", status: "complete", progressPercent: 100, trackId: "track-1" }))
		tracks.getTrack.mockResolvedValueOnce(track("track-1"))

		await useGenerationStore.getState().submitGeneration(req())
		expect(tracks.generateTrack).toHaveBeenCalledWith(req())
		expect(useGenerationStore.getState().currentJobId).toBe("job-1")
		expect(useGenerationStore.getState().isGenerating).toBe(true)

		await vi.advanceTimersByTimeAsync(2000)

		const s = useGenerationStore.getState()
		expect(s.jobStatus).toBe("complete")
		expect(s.currentTrack?.id).toBe("track-1")
		expect(s.isGenerating).toBe(false)
	})

	it("surfaces submit failures without polling", async () => {
		tracks.generateTrack.mockRejectedValueOnce(new Error("quota exhausted"))

		await useGenerationStore.getState().submitGeneration(req())

		const s = useGenerationStore.getState()
		expect(s.isGenerating).toBe(false)
		expect(s.jobStatus).toBe("failed")
		expect(s.error).toBe("quota exhausted")
		expect(tracks.getJobStatus).not.toHaveBeenCalled()
	})

	it("forwards user lyrics through the request", async () => {
		tracks.generateTrack.mockResolvedValueOnce(submitResponse("job-9"))

		await useGenerationStore.getState().submitGeneration(req({ lyrics: "[HOOK]\nJaiye" }))

		expect(tracks.generateTrack).toHaveBeenCalledWith(
			expect.objectContaining({ lyrics: "[HOOK]\nJaiye" }),
		)
	})
})

describe("submitRenditions", () => {
	it("starts N jobs with distinct seeds and completes them", async () => {
		tracks.generateTrack
			.mockResolvedValueOnce(submitResponse("job-a"))
			.mockResolvedValueOnce(submitResponse("job-b"))
		tracks.getJobStatus.mockImplementation(async (id: string) =>
			job({ id, status: "complete", progressPercent: 100, trackId: `track-${id}` }),
		)
		tracks.getTrack.mockImplementation(async (id: string) => track(id))

		await useGenerationStore.getState().submitRenditions(req(), 2)

		const seeds = tracks.generateTrack.mock.calls.map((c) => c[0].seed)
		expect(seeds).toHaveLength(2)
		expect(new Set(seeds).size).toBe(2)
		expect(seeds.every((s) => typeof s === "number")).toBe(true)

		await vi.advanceTimersByTimeAsync(2000)

		const s = useGenerationStore.getState()
		expect(s.renditions).toHaveLength(2)
		expect(s.renditions.every((r) => r.status === "complete")).toBe(true)
		expect(s.isGeneratingRenditions).toBe(false)
		// First finished take becomes the current track
		expect(s.currentTrack?.id).toBe("track-job-a")
		expect(s.activeRenditionJobId).toBe("job-a")
	})

	it("keeps started takes when a later submit fails", async () => {
		tracks.generateTrack
			.mockResolvedValueOnce(submitResponse("job-a"))
			.mockRejectedValueOnce(new Error("quota exhausted"))
		tracks.getJobStatus.mockResolvedValue(job({ id: "job-a", status: "complete", progressPercent: 100, trackId: "track-a" }))
		tracks.getTrack.mockResolvedValueOnce(track("track-a"))

		await useGenerationStore.getState().submitRenditions(req(), 2)
		await vi.advanceTimersByTimeAsync(2000)

		const s = useGenerationStore.getState()
		expect(s.renditions).toHaveLength(1)
		expect(s.error).toMatch(/Only 1 of 2 renditions started/)
		expect(s.currentTrack?.id).toBe("track-a")
	})

	it("fails cleanly when no rendition starts", async () => {
		tracks.generateTrack.mockRejectedValue(new Error("quota exhausted"))

		await useGenerationStore.getState().submitRenditions(req(), 2)

		const s = useGenerationStore.getState()
		expect(s.renditions).toHaveLength(0)
		expect(s.isGenerating).toBe(false)
		expect(s.error).toBe("quota exhausted")
	})

	it("selectRendition swaps the current track", async () => {
		tracks.generateTrack
			.mockResolvedValueOnce(submitResponse("job-a"))
			.mockResolvedValueOnce(submitResponse("job-b"))
		tracks.getJobStatus.mockImplementation(async (id: string) =>
			job({ id, status: "complete", progressPercent: 100, trackId: `track-${id}` }),
		)
		tracks.getTrack.mockImplementation(async (id: string) => track(id))

		await useGenerationStore.getState().submitRenditions(req(), 2)
		await vi.advanceTimersByTimeAsync(2000)

		useGenerationStore.getState().selectRendition("job-b")
		const s = useGenerationStore.getState()
		expect(s.activeRenditionJobId).toBe("job-b")
		expect(s.currentTrack?.id).toBe("track-job-b")
	})

	it("cancelRenditions revokes pending jobs and clears state", async () => {
		tracks.generateTrack
			.mockResolvedValueOnce(submitResponse("job-a"))
			.mockRejectedValueOnce(new Error("quota exhausted"))
		tracks.getJobStatus.mockResolvedValue(job({ id: "job-a", status: "ml_generating", progressPercent: 30 }))
		tracks.cancelGeneration.mockResolvedValueOnce(undefined)

		await useGenerationStore.getState().submitRenditions(req(), 2)
		expect(useGenerationStore.getState().renditions).toHaveLength(1)

		await useGenerationStore.getState().cancelRenditions()

		expect(tracks.cancelGeneration).toHaveBeenCalledWith("job-a")
		const s = useGenerationStore.getState()
		expect(s.renditions).toHaveLength(0)
		expect(s.jobStatus).toBe("cancelled")
		expect(s.isGenerating).toBe(false)
	})
})
