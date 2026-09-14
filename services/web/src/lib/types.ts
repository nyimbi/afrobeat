// TypeScript types mirroring backend Pydantic schemas

export type SubscriptionTier = "free" | "creator" | "pro" | "label"

export type SubGenre =
	| "afropop"
	| "afrofusion"
	| "alte"
	| "amapiano_cross"
	| "uk_afrobeats"
	| "afrobeats"
	| "highlife"
	| "bongo_flava"
	| "soukous"
	| "mbalax"
	| "soca"
	| "calypso"
	| "gengetone"
	| "benga"
	| "taarab"
	| "afro_soca"

export type Language =
	| "english"
	| "pidgin"
	| "yoruba"
	| "igbo"
	| "mix"
	| "swahili"
	| "lingala"
	| "zulu"
	| "twi"

export type JobStatus =
	| "queued"
	| "ml_generating"
	| "audio_processing"
	| "uploading"
	| "complete"
	| "failed"
	| "cancelled"

export type TrackStatus = "draft" | "processing" | "ready" | "failed"

export interface User {
	id: string
	email: string
	fullName: string
	avatarUrl: string | null
	subscriptionTier: SubscriptionTier
	creditsRemaining: number
	createdAt: string
}

export interface Track {
	id: string
	userId: string
	title: string
	subGenre: SubGenre
	language: Language
	prompt: string
	durationSeconds: number
	bpm: number | null
	musicalKey: string | null
	audioUrl: string | null
	previewUrl: string | null
	coverArtUrl: string | null
	status: TrackStatus
	playCount: number
	createdAt: string
	updatedAt: string
}

// Mirrors backend GenerationJobResponse (camelCase aliases). POST submit
// also includes statusMessage + estimatedSeconds; absent on GET.
export interface GenerationResponse {
	id: string
	status: JobStatus
	progressPercent: number
	statusMessage: string
	estimatedSeconds: number | null
}

export interface GenerationJob {
	id: string
	status: JobStatus
	progressPercent: number
	promptUsed: string
	modelUsed: string | null
	errorMessage: string | null
	trackId: string | null
	createdAt: string
	startedAt: string | null
	completedAt: string | null
}

// Mirrors backend VoiceModelResponse (camelCase aliases).
export type VoiceModelStatus = "pending" | "training" | "ready" | "failed" | "deprecated"

export interface VoiceModel {
	id: string
	name: string
	description: string | null
	archetype: string
	status: VoiceModelStatus
	isPreset: boolean
	isPublic: boolean
	trainingProgressPercent: number
	errorMessage: string | null
	createdAt: string
}

export interface BeatListing {
	id: string
	producerId: string
	producerName: string
	title: string
	subGenre: SubGenre
	bpm: number
	musicalKey: string
	durationSeconds: number
	previewUrl: string
	price: number
	currency: "USD" | "NGN"
	licenseType: "basic" | "exclusive"
	purchaseCount: number
	createdAt: string
}

export interface GenerationRequest {
	prompt: string
	subGenre: SubGenre
	language: Language
	energyLevel: number
	durationSeconds: number
	bpm: number | null
	voiceModelId: string | null
	// Optional user-supplied lyrics — skips AI lyric generation.
	lyrics: string | null
	// Optional RNG seed — same prompt + same seed reproduces a rendition.
	seed: number | null
	// Optional R2 key from the reference-track upload — steers tempo/key/feel.
	referenceAudioKey: string | null
}

export interface Rendition {
	jobId: string
	seed: number
	status: JobStatus | null
	progressPercent: number
	statusMessage: string
	trackId: string | null
	track: Track | null
	error: string | null
}

export interface LyricDraft {
	verse1: string
	prehook: string
	hook: string
	verse2: string
	bridge: string
	outro: string
	fullLyrics: string
	languageUsed: string
	fellBackToEnglish: boolean
	structureRetries?: number
	languageDisclosure: string | null
}

export type LyricsMode = "describe" | "write" | "ai"

export interface ApiError {
	code: string
	message: string
	details: Record<string, unknown> | null
	statusCode: number
}

export interface PaginatedResponse<T> {
	items: T[]
	total: number
	page: number
	pageSize: number
	hasMore: boolean
}

export interface AuthTokens {
	accessToken: string
	refreshToken: string
	expiresAt: number
}

export interface LoginRequest {
	email: string
	password: string
}

export interface RegisterRequest {
	email: string
	password: string
	fullName: string
}

export interface AuthResponse {
	user: Partial<User>
	tokens: AuthTokens
}
