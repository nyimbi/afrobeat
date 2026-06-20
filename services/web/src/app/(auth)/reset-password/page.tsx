"use client"

import { Suspense, useState } from "react"
import { useSearchParams } from "next/navigation"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import Link from "next/link"
import { Music2, Eye, EyeOff, CheckCircle2, Loader2 } from "lucide-react"
import { api, GbeduError } from "@/lib/api"

const schema = z
	.object({
		newPassword: z.string().min(8, "Must be at least 8 characters"),
		confirmPassword: z.string(),
	})
	.refine((d) => d.newPassword === d.confirmPassword, {
		message: "Passwords don't match",
		path: ["confirmPassword"],
	})

type FormData = z.infer<typeof schema>

function ResetPasswordContent() {
	const searchParams = useSearchParams()
	const token = searchParams.get("token") ?? ""
	const [showPw, setShowPw] = useState(false)
	const [done, setDone] = useState(false)
	const [serverError, setServerError] = useState("")

	const {
		register,
		handleSubmit,
		formState: { errors, isSubmitting },
	} = useForm<FormData>({ resolver: zodResolver(schema) })

	if (!token) {
		return (
			<div className="glass rounded-2xl p-6 w-full max-w-sm space-y-4 text-center">
				<p className="text-red-400 text-sm" role="alert">
					Invalid reset link. Request a new one from the login page.
				</p>
				<Link
					href="/forgot-password"
					className="block w-full py-3 rounded-xl bg-afro-gold text-dark-bg-primary font-semibold text-sm text-center cursor-pointer hover:bg-afro-gold-300 transition-all"
				>
					Request new link
				</Link>
			</div>
		)
	}

	if (done) {
		return (
			<div className="glass rounded-2xl p-6 w-full max-w-sm space-y-4 text-center animate-fade-in">
				<CheckCircle2 className="w-12 h-12 text-afro-gold mx-auto" />
				<h2 className="text-lg font-semibold text-zinc-100">Password updated</h2>
				<p className="text-zinc-400 text-sm">You can now sign in with your new password.</p>
				<Link
					href="/login"
					className="block w-full py-3 rounded-xl bg-afro-gold text-dark-bg-primary font-semibold text-sm text-center cursor-pointer hover:bg-afro-gold-300 transition-all"
				>
					Sign in
				</Link>
			</div>
		)
	}

	async function onSubmit(data: FormData) {
		setServerError("")
		try {
			await api.auth.resetPassword(token, data.newPassword)
			setDone(true)
		} catch (err) {
			setServerError(err instanceof GbeduError ? err.message : "Failed to reset password. Try requesting a new link.")
		}
	}

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

			<div className="glass rounded-2xl p-6 space-y-5">
				<div>
					<h2 className="text-lg font-semibold text-zinc-100">Set new password</h2>
					<p className="text-xs text-zinc-500 mt-0.5">Minimum 8 characters</p>
				</div>

				<form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
					<div className="space-y-1">
						<label className="text-xs font-medium text-zinc-400">New password</label>
						<div className="relative">
							<input
								{...register("newPassword")}
								type={showPw ? "text" : "password"}
								placeholder="••••••••"
								autoComplete="new-password"
								className="w-full px-3 py-3 pr-10 rounded-lg bg-dark-bg-elevated border border-white/[0.08] text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-afro-gold/60 transition-all"
							/>
							<button
								type="button"
								onClick={() => setShowPw((v) => !v)}
								aria-label={showPw ? "Hide password" : "Show password"}
								className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-colors cursor-pointer"
							>
								{showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
							</button>
						</div>
						{errors.newPassword && (
							<p className="text-xs text-red-400">{errors.newPassword.message}</p>
						)}
					</div>

					<div className="space-y-1">
						<label className="text-xs font-medium text-zinc-400">Confirm password</label>
						<input
							{...register("confirmPassword")}
							type={showPw ? "text" : "password"}
							placeholder="••••••••"
							autoComplete="new-password"
							className="w-full px-3 py-3 rounded-lg bg-dark-bg-elevated border border-white/[0.08] text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-afro-gold/60 transition-all"
						/>
						{errors.confirmPassword && (
							<p className="text-xs text-red-400">{errors.confirmPassword.message}</p>
						)}
					</div>

					{serverError && (
						<p className="text-xs text-red-400" role="alert">
							{serverError}
						</p>
					)}

					<button
						type="submit"
						disabled={isSubmitting}
						className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-afro-gold text-dark-bg-primary font-semibold text-sm hover:bg-afro-gold-300 hover:shadow-gold transition-all disabled:opacity-60 cursor-pointer"
					>
						{isSubmitting ? (
							<>
								<Loader2 className="w-4 h-4 animate-spin" />
								Updating&hellip;
							</>
						) : (
							"Update password"
						)}
					</button>
				</form>

				<p className="text-center text-xs text-zinc-500">
					<Link href="/login" className="text-afro-gold hover:underline cursor-pointer">
						Back to login
					</Link>
				</p>
			</div>
		</div>
	)
}

export default function ResetPasswordPage() {
	return (
		<div className="min-h-dvh flex flex-col items-center justify-center px-4 py-12 relative">
			<div
				className="absolute inset-0"
				style={{ background: "radial-gradient(ellipse at 50% 0%, rgba(212,175,55,0.07) 0%, transparent 70%)" }}
			/>
			<div className="absolute inset-0 adire-texture opacity-20" />
			<Suspense
				fallback={
					<div className="glass rounded-2xl p-8">
						<Loader2 className="w-5 h-5 text-afro-gold animate-spin" />
					</div>
				}
			>
				<ResetPasswordContent />
			</Suspense>
		</div>
	)
}
