"use client"

import { Suspense, useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import Link from "next/link"
import { CheckCircle2, XCircle, Music2, Loader2 } from "lucide-react"
import { api, GbeduError } from "@/lib/api"

type VerifyState = "loading" | "verified" | "error"

function VerifyEmailContent() {
	const searchParams = useSearchParams()
	const token = searchParams.get("token")
	const missingTokenMessage = "No verification token found. Use the link from your email."
	const [state, setState] = useState<VerifyState>(token ? "loading" : "error")
	const [errorMsg, setErrorMsg] = useState(token ? "" : missingTokenMessage)

	useEffect(() => {
		if (!token) {
			return
		}
		api.auth
			.verifyEmail(token)
			.then(() => setState("verified"))
			.catch((err: unknown) => {
				setErrorMsg(err instanceof GbeduError ? err.message : "Verification failed. The link may have expired.")
				setState("error")
			})
	}, [token])

	return (
		<div className="w-full max-w-sm space-y-5">
			<div className="flex flex-col items-center gap-2">
				<div className="flex items-center justify-center w-10 h-10 rounded-xl bg-afro-gold/10 border border-afro-gold/30">
					<Music2 className="w-5 h-5 text-afro-gold" />
				</div>
				<h1
					className="font-display text-2xl font-bold text-zinc-100"
					style={{ textShadow: "0 0 20px rgba(212,175,55,0.4)" }}
				>
					Gbẹdu
				</h1>
			</div>

			<div className="glass rounded-2xl p-6 space-y-4 animate-fade-in text-center">
				{state === "loading" && (
					<>
						<Loader2 className="w-10 h-10 text-afro-gold animate-spin mx-auto" />
						<p className="text-zinc-400 text-sm">Verifying your email&hellip;</p>
					</>
				)}

				{state === "verified" && (
					<>
						<CheckCircle2 className="w-12 h-12 text-afro-gold mx-auto" />
						<h2 className="text-lg font-semibold text-zinc-100">Email verified</h2>
						<p className="text-zinc-400 text-sm">Your account is active. Let&apos;s make something.</p>
						<Link
							href="/login"
							className="block w-full py-3 rounded-xl bg-afro-gold text-dark-bg-primary font-semibold text-sm hover:bg-afro-gold-300 hover:shadow-gold transition-all cursor-pointer text-center"
						>
							Continue to Studio
						</Link>
					</>
				)}

				{state === "error" && (
					<>
						<XCircle className="w-12 h-12 text-red-400 mx-auto" />
						<h2 className="text-lg font-semibold text-zinc-100">Verification failed</h2>
						<p className="text-red-400 text-sm" role="alert">
							{errorMsg}
						</p>
						<p className="text-zinc-500 text-xs">
							Verification links expire after 24&nbsp;hours. Request a new one from the login page.
						</p>
						<Link
							href="/login"
							className="block w-full py-3 rounded-xl bg-dark-bg-elevated border border-white/[0.08] text-zinc-300 font-semibold text-sm hover:border-afro-gold/40 transition-all cursor-pointer text-center"
						>
							Back to login
						</Link>
					</>
				)}
			</div>
		</div>
	)
}

export default function VerifyEmailPage() {
	return (
		<div className="min-h-dvh flex flex-col items-center justify-center px-4 py-12 relative">
			<div
				className="absolute inset-0"
				style={{ background: "radial-gradient(ellipse at 50% 0%, rgba(212,175,55,0.07) 0%, transparent 70%)" }}
			/>
			<div className="absolute inset-0 adire-texture opacity-20" />
			<Suspense
				fallback={
					<div className="glass rounded-2xl p-8 flex items-center gap-3">
						<Loader2 className="w-5 h-5 text-afro-gold animate-spin" />
						<span className="text-zinc-400 text-sm">Loading&hellip;</span>
					</div>
				}
			>
				<VerifyEmailContent />
			</Suspense>
		</div>
	)
}
