import NextAuth, { NextAuthOptions, Session, User as NextAuthUser } from "next-auth"
import GoogleProvider from "next-auth/providers/google"
import CredentialsProvider from "next-auth/providers/credentials"
import { JWT } from "next-auth/jwt"
import type { SubscriptionTier } from "@/lib/types"

// Extend next-auth types
declare module "next-auth" {
	interface Session {
		accessToken: string
		refreshToken: string
		subscriptionTier: SubscriptionTier
		user: {
			id: string
			email: string
			name: string
			image: string | null
			subscriptionTier: SubscriptionTier
		}
	}
	interface User {
		accessToken?: string
		refreshToken?: string
		subscriptionTier?: SubscriptionTier
	}
}

declare module "next-auth/jwt" {
	interface JWT {
		accessToken?: string
		refreshToken?: string
		expiresAt?: number
		subscriptionTier?: SubscriptionTier
		userId?: string
	}
}

const authOptions: NextAuthOptions = {
	providers: [
		GoogleProvider({
			clientId: process.env.GOOGLE_CLIENT_ID ?? "",
			clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? "",
		}),

		CredentialsProvider({
			name: "credentials",
			credentials: {
				email: { label: "Email", type: "email" },
				password: { label: "Password", type: "password" },
			},
			async authorize(credentials) {
				if (!credentials?.email || !credentials?.password) return null

				try {
					const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
					const res = await fetch(`${apiUrl}/auth/login`, {
						method: "POST",
						headers: { "Content-Type": "application/json" },
						body: JSON.stringify({
							email: credentials.email,
							password: credentials.password,
						}),
					})

					if (!res.ok) return null

					const data = await res.json() as {
						user: { id: string; email: string; fullName: string; avatarUrl: string | null; subscriptionTier: SubscriptionTier }
						tokens: { accessToken: string; refreshToken: string; expiresAt: number }
					}

					return {
						id: data.user.id,
						email: data.user.email,
						name: data.user.fullName,
						image: data.user.avatarUrl,
						accessToken: data.tokens.accessToken,
						refreshToken: data.tokens.refreshToken,
						subscriptionTier: data.user.subscriptionTier,
					} satisfies NextAuthUser
				} catch {
					return null
				}
			},
		}),
	],

	session: {
		strategy: "jwt",
		maxAge: 30 * 24 * 60 * 60, // 30 days
	},

	callbacks: {
		async jwt({ token, user, account }) {
			// Initial sign in
			if (user) {
				token.userId = user.id
				token.subscriptionTier = user.subscriptionTier ?? "free"
				if (user.accessToken) token.accessToken = user.accessToken
				if (user.refreshToken) token.refreshToken = user.refreshToken
			}

			// Google OAuth — exchange Google token for backend token
			if (account?.provider === "google" && account.access_token) {
				try {
					const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
					const res = await fetch(`${apiUrl}/auth/google`, {
						method: "POST",
						headers: { "Content-Type": "application/json" },
						body: JSON.stringify({ googleToken: account.access_token }),
					})
					if (res.ok) {
						const data = await res.json() as {
							user: { id: string; subscriptionTier: SubscriptionTier }
							tokens: { accessToken: string; refreshToken: string; expiresAt: number }
						}
						token.userId = data.user.id
						token.subscriptionTier = data.user.subscriptionTier
						token.accessToken = data.tokens.accessToken
						token.refreshToken = data.tokens.refreshToken
						token.expiresAt = data.tokens.expiresAt
					}
				} catch {
					// Fall through — token without backend auth
				}
			}

			return token
		},

		async session({ session, token }: { session: Session; token: JWT }) {
			const s = session as Session & { accessToken: string; refreshToken: string; subscriptionTier: SubscriptionTier }
			s.accessToken = token.accessToken ?? ""
			s.refreshToken = token.refreshToken ?? ""
			s.subscriptionTier = token.subscriptionTier ?? "free"
			if (s.user) {
				s.user.id = token.userId ?? token.sub ?? ""
				s.user.subscriptionTier = token.subscriptionTier ?? "free"
			}
			return s
		},
	},

	pages: {
		signIn: "/login",
		error: "/login",
	},

	secret: process.env.NEXTAUTH_SECRET ?? "dev-secret-replace-in-production",
}

const handler = NextAuth(authOptions)
export { handler as GET, handler as POST }
