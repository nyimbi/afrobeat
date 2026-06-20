"use client"

import { useState } from "react"
import Link from "next/link"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Music2, Loader2, ArrowLeft, CheckCircle2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"

const schema = z.object({
	email: z.string().email("Enter a valid email"),
})

type FormData = z.infer<typeof schema>

export default function ForgotPasswordPage() {
	const [sent, setSent] = useState(false)
	const [sentEmail, setSentEmail] = useState("")

	const {
		register,
		handleSubmit,
		formState: { errors, isSubmitting },
	} = useForm<FormData>({ resolver: zodResolver(schema) })

	async function onSubmit(data: FormData) {
		await api.auth.forgotPassword(data.email)
		setSentEmail(data.email)
		setSent(true)
	}

	return (
		<div className="min-h-dvh flex flex-col items-center justify-center px-4 py-12 relative">
			<div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_60%_at_50%_-10%,rgba(212,175,55,0.07),transparent)]" />
			<div className="absolute inset-0 adire-texture opacity-20" />

			<div className="relative w-full max-w-sm space-y-8">
				{/* Logo */}
				<div className="text-center space-y-3">
					<Link href="/" className="inline-flex items-center gap-2.5">
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
				</div>

				{sent ? (
					<div className="glass rounded-2xl p-6 space-y-4 text-center animate-fade-in">
						<CheckCircle2 className="w-10 h-10 text-afro-gold mx-auto" />
						<div>
							<h1 className="font-display text-xl font-bold text-zinc-100">Check your inbox</h1>
							<p className="text-sm text-zinc-500 mt-2">
								We sent a reset link to{" "}
								<span className="text-zinc-300 font-medium">{sentEmail}</span>.
								It expires in 15 minutes.
							</p>
						</div>
						<p className="text-xs text-zinc-600">
							Didn&apos;t get it? Check spam, or{" "}
							<button
								onClick={() => setSent(false)}
								className="text-afro-gold hover:text-afro-gold-300 transition-colors cursor-pointer"
							>
								try again
							</button>
							.
						</p>
					</div>
				) : (
					<div className="glass rounded-2xl p-6 space-y-5">
						<div>
							<h1 className="font-display text-xl font-bold text-zinc-100">Reset your password</h1>
							<p className="text-sm text-zinc-500 mt-1">
								Enter your email and we&apos;ll send a reset link.
							</p>
						</div>

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
										"w-full px-3 py-3 rounded-lg bg-dark-bg-elevated border text-sm text-zinc-100 placeholder:text-zinc-600",
										"focus:outline-none focus:ring-1 focus:ring-afro-gold/60 transition-all",
										errors.email ? "border-red-500/60" : "border-white/[0.08]",
									)}
									placeholder="you@example.com"
								/>
								{errors.email && (
									<p className="text-xs text-red-400">{errors.email.message}</p>
								)}
							</div>

							<button
								type="submit"
								disabled={isSubmitting}
								className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-afro-gold text-dark-bg-primary font-semibold text-sm hover:bg-afro-gold-300 hover:shadow-gold transition-all disabled:opacity-60 cursor-pointer"
							>
								{isSubmitting ? (
									<><Loader2 className="w-4 h-4 animate-spin" />Sending link...</>
								) : (
									"Send reset link"
								)}
							</button>
						</form>
					</div>
				)}

				<p className="text-center text-sm text-zinc-600">
					<Link
						href="/login"
						className="inline-flex items-center gap-1.5 text-zinc-500 hover:text-zinc-300 transition-colors"
					>
						<ArrowLeft className="w-3.5 h-3.5" />
						Back to sign in
					</Link>
				</p>
			</div>
		</div>
	)
}
