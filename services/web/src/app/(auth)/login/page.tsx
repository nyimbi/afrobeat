"use client"

import { useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { signIn } from "next-auth/react"
import { Eye, EyeOff, Music2, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

const loginSchema = z.object({
	email: z.string().email("Enter a valid email"),
	password: z.string().min(8, "Password must be at least 8 characters"),
})

type LoginFormData = z.infer<typeof loginSchema>

export default function LoginPage() {
	const router = useRouter()
	const [showPassword, setShowPassword] = useState(false)
	const [isGoogleLoading, setIsGoogleLoading] = useState(false)
	const [serverError, setServerError] = useState<string | null>(null)

	const {
		register,
		handleSubmit,
		formState: { errors, isSubmitting },
	} = useForm<LoginFormData>({ resolver: zodResolver(loginSchema) })

	async function onSubmit(data: LoginFormData) {
		setServerError(null)
		const res = await signIn("credentials", {
			email: data.email,
			password: data.password,
			redirect: false,
		})
		if (res?.error) {
			setServerError("Invalid email or password. Please try again.")
			return
		}
		router.push("/studio")
	}

	async function handleGoogleSignIn() {
		setIsGoogleLoading(true)
		await signIn("google", { callbackUrl: "/studio" })
	}

	return (
		<div className="min-h-dvh flex flex-col items-center justify-center px-4 py-12 relative">
			{/* Background radial glow */}
			<div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_60%_at_50%_-10%,rgba(212,175,55,0.07),transparent)]" />
			<div className="absolute inset-0 adire-texture opacity-20" />

			<div className="relative w-full max-w-sm space-y-8">
				{/* Logo */}
				<div className="text-center space-y-3">
					<Link href="/" className="inline-flex items-center gap-2.5 group">
						<div className="w-10 h-10 rounded-xl bg-afro-gold/10 border border-afro-gold/30 flex items-center justify-center">
							<Music2 className="w-5 h-5 text-afro-gold" />
						</div>
						<span
							className="font-display text-2xl font-bold"
							style={{ color: "#D4AF37", textShadow: "0 0 20px rgba(212,175,55,0.35)" }}
						>
							Gbẹdu
						</span>
					</Link>
					<div>
						<h1 className="font-display text-2xl font-bold text-zinc-100">Welcome back</h1>
						<p className="text-sm text-zinc-500 mt-1">Sign in to your studio</p>
					</div>
				</div>

				{/* Card */}
				<div className="glass rounded-2xl p-6 space-y-5">
					{/* Google button */}
					<button
						onClick={handleGoogleSignIn}
						disabled={isGoogleLoading || isSubmitting}
						className="w-full flex items-center justify-center gap-3 py-2.5 rounded-xl border border-white/[0.10] bg-white/[0.04] hover:bg-white/[0.08] text-sm font-medium text-zinc-200 transition-all disabled:opacity-60"
					>
						{isGoogleLoading ? (
							<Loader2 className="w-4 h-4 animate-spin" />
						) : (
							<svg className="w-4 h-4" viewBox="0 0 24 24" aria-hidden>
								<path
									fill="#4285F4"
									d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
								/>
								<path
									fill="#34A853"
									d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
								/>
								<path
									fill="#FBBC05"
									d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
								/>
								<path
									fill="#EA4335"
									d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
								/>
							</svg>
						)}
						Continue with Google
					</button>

					{/* Divider */}
					<div className="relative flex items-center gap-3">
						<div className="flex-1 h-px bg-white/[0.07]" />
						<span className="text-[10px] uppercase tracking-widest text-zinc-600">or</span>
						<div className="flex-1 h-px bg-white/[0.07]" />
					</div>

					{/* Email/password form */}
					<form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
						<div className="space-y-1.5">
							<label className="text-xs font-medium text-zinc-400" htmlFor="email">
								Email
							</label>
							<input
								{...register("email")}
								id="email"
								type="email"
								autoComplete="email"
								className={cn(
									"w-full px-3 py-2.5 rounded-lg bg-dark-bg-elevated border text-sm text-zinc-100 placeholder:text-zinc-600",
									"focus:outline-none focus:ring-1 focus:ring-afro-gold/60 transition-all",
									errors.email ? "border-red-500/60" : "border-white/[0.08]",
								)}
								placeholder="you@example.com"
							/>
							{errors.email && (
								<p className="text-xs text-red-400">{errors.email.message}</p>
							)}
						</div>

						<div className="space-y-1.5">
							<div className="flex items-center justify-between">
								<label className="text-xs font-medium text-zinc-400" htmlFor="password">
									Password
								</label>
								<Link
									href="/forgot-password"
									className="text-xs text-afro-gold/70 hover:text-afro-gold transition-colors"
								>
									Forgot password?
								</Link>
							</div>
							<div className="relative">
								<input
									{...register("password")}
									id="password"
									type={showPassword ? "text" : "password"}
									autoComplete="current-password"
									className={cn(
										"w-full px-3 py-2.5 pr-10 rounded-lg bg-dark-bg-elevated border text-sm text-zinc-100 placeholder:text-zinc-600",
										"focus:outline-none focus:ring-1 focus:ring-afro-gold/60 transition-all",
										errors.password ? "border-red-500/60" : "border-white/[0.08]",
									)}
									placeholder="••••••••"
								/>
								<button
									type="button"
									onClick={() => setShowPassword((v) => !v)}
									className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-600 hover:text-zinc-400 transition-colors"
									aria-label={showPassword ? "Hide password" : "Show password"}
								>
									{showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
								</button>
							</div>
							{errors.password && (
								<p className="text-xs text-red-400">{errors.password.message}</p>
							)}
						</div>

						{serverError && (
							<div className="rounded-lg bg-red-500/10 border border-red-500/20 px-3 py-2">
								<p className="text-xs text-red-400">{serverError}</p>
							</div>
						)}

						<button
							type="submit"
							disabled={isSubmitting || isGoogleLoading}
							className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-afro-gold text-dark-bg-primary font-semibold text-sm hover:bg-afro-gold-300 transition-colors disabled:opacity-60 animate-pulse-gold"
						>
							{isSubmitting ? (
								<Loader2 className="w-4 h-4 animate-spin" />
							) : (
								"Sign in"
							)}
						</button>
					</form>
				</div>

				<p className="text-center text-sm text-zinc-600">
					No account?{" "}
					<Link href="/register" className="text-afro-gold hover:text-afro-gold-300 font-medium transition-colors">
						Create one free
					</Link>
				</p>
			</div>
		</div>
	)
}
