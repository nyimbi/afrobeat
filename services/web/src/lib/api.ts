import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from "axios"
import type {
	Track,
	GenerationJob,
	GenerationRequest,
	GenerationResponse,
	BeatListing,
	LyricDraft,
	VoiceModel,
	PaginatedResponse,
	AuthResponse,
	LoginRequest,
	RegisterRequest,
	User,
} from "./types"

// ---- Error normalization ----

export class GbeduError extends Error {
	code: string
	statusCode: number
	details: Record<string, unknown> | null

	constructor(
		message: string,
		code: string,
		statusCode: number,
		details: Record<string, unknown> | null = null,
	) {
		super(message)
		this.name = "GbeduError"
		this.code = code
		this.statusCode = statusCode
		this.details = details
	}
}

function normalizeError(err: AxiosError): GbeduError {
	const status = err.response?.status ?? 0
	const data = err.response?.data as Record<string, unknown> | undefined
	const message =
		typeof data?.message === "string" ? data.message : err.message
	const code = typeof data?.code === "string" ? data.code : "UNKNOWN_ERROR"
	const details =
		data?.details && typeof data.details === "object"
			? (data.details as Record<string, unknown>)
			: null
	return new GbeduError(message, code, status, details)
}

// ---- Token store accessor (injected to break circular dep) ----

type TokenGetter = () => { accessToken: string | null; refreshToken: string | null }
type TokenSetter = (tokens: { accessToken: string; refreshToken: string; expiresAt: number }) => void
type LogoutFn = () => void

let _getTokens: TokenGetter = () => ({ accessToken: null, refreshToken: null })
let _setTokens: TokenSetter = () => {}
let _logout: LogoutFn = () => {}

export function configureApiAuth(
	getTokens: TokenGetter,
	setTokens: TokenSetter,
	logout: LogoutFn,
) {
	_getTokens = getTokens
	_setTokens = setTokens
	_logout = logout
}

// ---- Axios instance ----
// Backend mounts all routers under /api/v1 (see api/main.py). Normalise the
// env var so both "http://host:8000" and "http://host:8000/api/v1" work.
function resolveApiBaseUrl(): string {
	const raw = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "")
	return raw.endsWith("/api/v1") ? raw : `${raw}/api/v1`
}

export function getApiBaseUrl(): string {
	return resolveApiBaseUrl()
}

export const apiClient: AxiosInstance = axios.create({
	baseURL: resolveApiBaseUrl(),
	timeout: 30_000,
	headers: { "Content-Type": "application/json" },
})

// Request interceptor — attach Bearer token
apiClient.interceptors.request.use(
	(config: InternalAxiosRequestConfig) => {
		const { accessToken } = _getTokens()
		if (accessToken) {
			config.headers.Authorization = `Bearer ${accessToken}`
		}
		return config
	},
	(err: AxiosError) => Promise.reject(normalizeError(err)),
)

// Track if we're already refreshing to avoid race conditions
let isRefreshing = false
let refreshQueue: Array<(token: string) => void> = []

function processQueue(newToken: string) {
	refreshQueue.forEach((cb) => cb(newToken))
	refreshQueue = []
}

// Response interceptor — 401 → refresh and retry once, normalize errors
apiClient.interceptors.response.use(
	(res) => res,
	async (err: AxiosError) => {
		const original = err.config as InternalAxiosRequestConfig & { _retry?: boolean }

		if (err.response?.status === 401 && !original._retry) {
			const { refreshToken } = _getTokens()
			if (!refreshToken) {
				_logout()
				return Promise.reject(normalizeError(err))
			}

			if (isRefreshing) {
				return new Promise<string>((resolve) => {
					refreshQueue.push(resolve)
				}).then((newToken) => {
					original.headers.Authorization = `Bearer ${newToken}`
					return apiClient(original)
				})
			}

			original._retry = true
			isRefreshing = true

			try {
				const res = await axios.post<{ accessToken: string; refreshToken: string; expiresAt: number }>(
					`${resolveApiBaseUrl()}/auth/refresh`,
					{ refreshToken },
				)
				const tokens = res.data
				_setTokens(tokens)
				processQueue(tokens.accessToken)
				original.headers.Authorization = `Bearer ${tokens.accessToken}`
				return apiClient(original)
			} catch {
				_logout()
				return Promise.reject(normalizeError(err))
			} finally {
				isRefreshing = false
			}
		}

		return Promise.reject(normalizeError(err))
	},
)

// ---- Typed endpoint methods ----

export const api = {
	auth: {
		async login(req: LoginRequest): Promise<AuthResponse> {
			const res = await apiClient.post<AuthResponse>("/auth/login", req)
			return res.data
		},

		async register(req: RegisterRequest): Promise<AuthResponse> {
			const res = await apiClient.post<AuthResponse>("/auth/register", req)
			return res.data
		},

		async refreshTokens(refreshToken: string): Promise<{ accessToken: string; refreshToken: string; expiresAt: number }> {
			const res = await apiClient.post("/auth/refresh", { refreshToken })
			return res.data
		},

		async getMe(): Promise<User> {
			const res = await apiClient.get<User>("/users/me")
			return res.data
		},

		async updateProfile(data: Partial<Pick<User, "fullName" | "avatarUrl">>): Promise<User> {
			const res = await apiClient.patch<User>("/users/me", data)
			return res.data
		},

		async forgotPassword(email: string): Promise<void> {
			await apiClient.post("/auth/forgot-password", { email })
		},

		async resetPassword(token: string, newPassword: string): Promise<void> {
			await apiClient.post("/auth/reset-password", { token, new_password: newPassword })
		},

		async verifyEmail(token: string): Promise<void> {
			await apiClient.post("/auth/verify-email", { token })
		},
	},

	tracks: {
		async generateTrack(req: GenerationRequest): Promise<GenerationResponse> {
			const res = await apiClient.post<GenerationResponse>("/generations", req)
			return res.data
		},

		async getJobStatus(jobId: string): Promise<GenerationJob> {
			const res = await apiClient.get<GenerationJob>(`/generations/${jobId}`)
			return res.data
		},

		async cancelGeneration(jobId: string): Promise<void> {
			await apiClient.delete(`/generations/${jobId}`)
		},

		async uploadReference(file: File): Promise<{ key: string }> {
			const form = new FormData()
			form.append("file", file)
			const res = await apiClient.post<{ key: string }>("/generations/reference", form, {
				headers: { "Content-Type": "multipart/form-data" },
				timeout: 120_000,
			})
			return res.data
		},

		async getTracks(params: { page?: number; pageSize?: number; subGenre?: string | undefined; language?: string | undefined; search?: string | undefined } = {}): Promise<PaginatedResponse<Track>> {
			const res = await apiClient.get<PaginatedResponse<Track>>("/tracks", { params })
			return res.data
		},

		async getTrack(trackId: string): Promise<Track> {
			const res = await apiClient.get<Track>(`/tracks/${trackId}`)
			return res.data
		},

		async deleteTrack(trackId: string): Promise<void> {
			await apiClient.delete(`/tracks/${trackId}`)
		},

		async incrementPlayCount(trackId: string): Promise<void> {
			await apiClient.post(`/tracks/${trackId}/play`)
		},

		async getDownloadUrl(trackId: string, format: "mp3" | "wav" = "mp3"): Promise<{ url: string; expiresAt: number }> {
			const res = await apiClient.get(`/tracks/${trackId}/download`, { params: { format } })
			return res.data
		},

		async getStems(trackId: string): Promise<{ trackId: string; stems: Record<string, string> }> {
			const res = await apiClient.get<{ trackId: string; stems: Record<string, string> }>(`/tracks/${trackId}/stems`)
			return res.data
		},

		async updateTrack(trackId: string, data: { title?: string; isPublic?: boolean }): Promise<Track> {
			const res = await apiClient.patch<Track>(`/tracks/${trackId}`, data)
			return res.data
		},
	},

	lyrics: {
		async draftLyrics(req: { prompt: string; subGenre: string; language: string }): Promise<LyricDraft> {
			const res = await apiClient.post<LyricDraft>("/lyrics/draft", req)
			return res.data
		},
	},

	marketplace: {
		async getBeats(params: { page?: number; pageSize?: number; subGenre?: string | undefined; bpmMin?: number | undefined; bpmMax?: number | undefined; key?: string | undefined; priceMax?: number | undefined } = {}): Promise<PaginatedResponse<BeatListing>> {
			const res = await apiClient.get<PaginatedResponse<BeatListing>>("/marketplace/beats", { params })
			return res.data
		},

		async getBeat(beatId: string): Promise<BeatListing> {
			const res = await apiClient.get<BeatListing>(`/marketplace/beats/${beatId}`)
			return res.data
		},

		async purchaseBeat(beatId: string, paymentMethod: "stripe" | "paystack"): Promise<{ checkoutUrl: string }> {
			const res = await apiClient.post(`/marketplace/beats/${beatId}/purchase`, { paymentMethod })
			return res.data
		},
	},

	voices: {
		async getVoiceModels(): Promise<VoiceModel[]> {
			const res = await apiClient.get<VoiceModel[]>("/voice-models")
			return res.data
		},

		async getVoiceModelStatus(modelId: string): Promise<VoiceModel> {
			const res = await apiClient.get<VoiceModel>(`/voice-models/${modelId}/status`)
			return res.data
		},

		async uploadVoiceModel(args: {
			name: string
			description?: string
			file: File
		}): Promise<VoiceModel> {
			const form = new FormData()
			form.append("name", args.name)
			if (args.description) form.append("description", args.description)
			form.append("file", args.file)
			const res = await apiClient.post<VoiceModel>("/voice-models/upload", form, {
				headers: { "Content-Type": "multipart/form-data" },
				timeout: 120_000,
			})
			return res.data
		},

		async deleteVoiceModel(modelId: string): Promise<void> {
			await apiClient.delete(`/voice-models/${modelId}`)
		},
	},

	payments: {
		async createCheckoutSession(tier: "creator" | "pro" | "label", provider: "stripe" | "paystack"): Promise<{ checkoutUrl: string }> {
			const res = await apiClient.post("/payments/subscribe", { tier, provider })
			return res.data
		},

		async cancelSubscription(): Promise<void> {
			await apiClient.post("/payments/cancel")
		},

		async createPortalSession(returnUrl: string): Promise<{ url: string }> {
			const res = await apiClient.post<{ url: string }>("/billing/portal-session", { return_url: returnUrl })
			return res.data
		},
	},
}
