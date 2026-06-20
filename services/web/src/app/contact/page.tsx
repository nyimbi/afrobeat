"use client"

import { useState } from "react"
import Link from "next/link"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { CheckCircle2, Loader2 } from "lucide-react"
import { apiClient, GbeduError } from "@/lib/api"

const schema = z.object({
	name: z.string().min(1, "Required").max(200),
	email: z.string().email("Enter a valid email"),
	subject: z.string().min(1, "Required").max(300),
	message: z.string().min(10, "At least 10 characters").max(5000),
})

type FormData = z.infer<typeof schema>

export default function ContactPage() {
	const [submitted, setSubmitted] = useState(false)
	const [serverError, setServerError] = useState("")

	const {
		register,
		handleSubmit,
		formState: { errors, isSubmitting },
	} = useForm<FormData>({ resolver: zodResolver(schema) })

	async function onSubmit(data: FormData) {
		setServerError("")
		try {
			await apiClient.post("/contact", data)
			setSubmitted(true)
		} catch (err) {
			setServerError(
				err instanceof GbeduError ? err.message : "Something went wrong. Please try again or email us directly.",
			)
		}
	}

	return (
		<div className="min-h-dvh px-4 py-16 relative">
			<div
				className="absolute inset-0"
				style={{ background: "radial-gradient(ellipse at 50% 0%, rgba(212,175,55,0.05) 0%, transparent 60%)" }}
			/>

			<div className="relative max-w-xl mx-auto space-y-8">
				<nav className="text-sm text-zinc-500">
					<Link href="/" className="hover:text-afro-gold transition-colors">
						Gbẹdu
					</Link>{" "}
					/ Contact
				</nav>

				<div>
					<p className="text-afro-gold text-sm font-medium mb-1">Support</p>
					<h1 className="font-display text-3xl font-bold text-zinc-100">Get in touch</h1>
					<p className="text-zinc-500 text-sm mt-1">
						We respond within one business day. For urgent issues:{" "}
						<a href="mailto:support@gbedu.io" className="text-afro-gold hover:underline">
							support@gbedu.io
						</a>
					</p>
				</div>

				{submitted ? (
					<div className="glass rounded-2xl p-8 text-center space-y-4 animate-fade-in">
						<CheckCircle2 className="w-12 h-12 text-afro-gold mx-auto" />
						<h2 className="text-lg font-semibold text-zinc-100">Message received</h2>
						<p className="text-zinc-400 text-sm">
							We&apos;ll get back to you at the address you provided within one business day.
						</p>
						<Link
							href="/"
							className="inline-block px-6 py-2.5 rounded-xl bg-afro-gold text-dark-bg-primary font-semibold text-sm hover:bg-afro-gold-300 transition-all cursor-pointer"
						>
							Back to Studio
						</Link>
					</div>
				) : (
					<form
						onSubmit={handleSubmit(onSubmit)}
						className="glass rounded-2xl p-6 space-y-5"
						noValidate
					>
						<div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
							<div className="space-y-1">
								<label className="text-xs font-medium text-zinc-400">
									Name <span className="text-red-400">*</span>
								</label>
								<input
									{...register("name")}
									type="text"
									placeholder="Your name"
									autoComplete="name"
									className="w-full px-3 py-3 rounded-lg bg-dark-bg-elevated border border-white/[0.08] text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-afro-gold/60 transition-all"
								/>
								{errors.name && <p className="text-xs text-red-400">{errors.name.message}</p>}
							</div>

							<div className="space-y-1">
								<label className="text-xs font-medium text-zinc-400">
									Email <span className="text-red-400">*</span>
								</label>
								<input
									{...register("email")}
									type="email"
									placeholder="you@example.com"
									autoComplete="email"
									className="w-full px-3 py-3 rounded-lg bg-dark-bg-elevated border border-white/[0.08] text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-afro-gold/60 transition-all"
								/>
								{errors.email && <p className="text-xs text-red-400">{errors.email.message}</p>}
							</div>
						</div>

						<div className="space-y-1">
							<label className="text-xs font-medium text-zinc-400">
								Subject <span className="text-red-400">*</span>
							</label>
							<input
								{...register("subject")}
								type="text"
								placeholder="What's this about?"
								className="w-full px-3 py-3 rounded-lg bg-dark-bg-elevated border border-white/[0.08] text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-afro-gold/60 transition-all"
							/>
							{errors.subject && <p className="text-xs text-red-400">{errors.subject.message}</p>}
						</div>

						<div className="space-y-1">
							<label className="text-xs font-medium text-zinc-400">
								Message <span className="text-red-400">*</span>
							</label>
							<textarea
								{...register("message")}
								rows={6}
								placeholder="Describe your issue or question in detail..."
								className="w-full px-3 py-3 rounded-lg bg-dark-bg-elevated border border-white/[0.08] text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-afro-gold/60 transition-all resize-none"
							/>
							{errors.message && <p className="text-xs text-red-400">{errors.message.message}</p>}
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
									Sending&hellip;
								</>
							) : (
								"Send message"
							)}
						</button>

						<p className="text-xs text-zinc-600 text-center">
							By submitting, you agree to our{" "}
							<Link href="/privacy" className="text-afro-gold hover:underline">
								Privacy Policy
							</Link>
							.
						</p>
					</form>
				)}
			</div>
		</div>
	)
}
