"use client"

import { create } from "zustand"
import type { StateCreator } from "zustand"
import { persist, createJSONStorage } from "zustand/middleware"
import { configureApiAuth } from "@/lib/api"
import type { User, AuthTokens } from "@/lib/types"

interface AuthState {
	user: User | null
	accessToken: string | null
	refreshToken: string | null
	expiresAt: number | null
	isAuthenticated: boolean
	isLoading: boolean

	// Actions
	login: (user: User, tokens: AuthTokens) => void
	logout: () => void
	refreshTokens: (tokens: { accessToken: string; refreshToken: string; expiresAt: number }) => void
	updateUser: (user: Partial<User>) => void
	setLoading: (loading: boolean) => void
	hydrate: () => void
}

const createAuthState: StateCreator<AuthState> = (set, get) => ({
	user: null,
	accessToken: null,
	refreshToken: null,
	expiresAt: null,
	isAuthenticated: false,
	isLoading: true,

	login(user, tokens) {
		set({
			user,
			accessToken: tokens.accessToken,
			refreshToken: tokens.refreshToken,
			expiresAt: tokens.expiresAt,
			isAuthenticated: true,
			isLoading: false,
		})
	},

	logout() {
		set({
			user: null,
			accessToken: null,
			refreshToken: null,
			expiresAt: null,
			isAuthenticated: false,
			isLoading: false,
		})
	},

	refreshTokens(tokens) {
		set({
			accessToken: tokens.accessToken,
			refreshToken: tokens.refreshToken,
			expiresAt: tokens.expiresAt,
		})
	},

	updateUser(partial) {
		const { user } = get()
		if (!user) return
		set({ user: { ...user, ...partial } })
	},

	setLoading(loading) {
		set({ isLoading: loading })
	},

	hydrate() {
		// Wire up the api client after hydration
		const store = get()
		configureApiAuth(
			() => ({ accessToken: get().accessToken, refreshToken: get().refreshToken }),
			(tokens) => get().refreshTokens(tokens),
			() => get().logout(),
		)
		// If token is expired, clear state
		if (store.expiresAt && store.expiresAt < Date.now()) {
			get().logout()
		} else {
			set({ isLoading: false })
		}
	},
})

const authStateCreator: StateCreator<AuthState> =
	typeof window === "undefined"
		? createAuthState
		: (persist(createAuthState, {
				name: "gbedu-auth",
				storage: createJSONStorage(() => window.localStorage),
				// Only persist auth tokens and user, not loading states
				partialize: (state) => ({
					user: state.user,
					accessToken: state.accessToken,
					refreshToken: state.refreshToken,
					expiresAt: state.expiresAt,
					isAuthenticated: state.isAuthenticated,
				}),
			}) as unknown as StateCreator<AuthState>)

export const useAuthStore = create<AuthState>()(authStateCreator)
