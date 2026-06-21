"use client"

import { useState } from "react"
import Link from "next/link"
import {
	Music2,
	CreditCard,
	Calendar,
	CheckCircle2,
	AlertCircle,
	ArrowLeft,
	Loader2,
} from "lucide-react"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

type PortalState = "idle" | "loading" | "error"

export default function BillingPage() {
	const [portalState, setPortalState] = useState<PortalState>("idle")

	async function openCustomerPortal() {
		setPortalState("loading")
		try {
			const { url } = await api.payments.createPortalSession(window.location.href)
			window.location.href = url
		} catch {
			setPortalState("error")
		}
	}

	return (
		<div className="min-h-dvh bg-gradient-to-b from-zinc-950 to-zinc-900 px-4 py-12">
			<div className="mx-auto w-full max-w-xl space-y-8">
				{/* Header */}
				<div className="space-y-1">
					<Link
						href="/studio"
						className="inline-flex items-center gap-1.5 text-zinc-500 hover:text-zinc-300 text-sm transition-colors mb-4"
					>
						<ArrowLeft className="h-4 w-4" aria-hidden />
						Back to Studio
					</Link>
					<div className="flex items-center gap-3">
						<Music2 className="h-7 w-7 text-emerald-400" aria-hidden />
						<h1 className="text-2xl font-bold text-white tracking-tight">
							Billing &amp; Subscription
						</h1>
					</div>
					<p className="text-zinc-400 text-sm">
						Manage your plan, payment method, and invoices.
					</p>
				</div>

				{/* Manage via Stripe portal */}
				<div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-6 space-y-4">
					<div className="flex items-start gap-4">
						<div className="mt-0.5 rounded-lg bg-zinc-800 p-2">
							<CreditCard className="h-5 w-5 text-zinc-300" aria-hidden />
						</div>
						<div className="flex-1 space-y-1">
							<h2 className="text-base font-semibold text-white">
								Customer Portal
							</h2>
							<p className="text-zinc-400 text-sm leading-relaxed">
								Update your payment method, download past invoices, or cancel
								your subscription — all through the secure Stripe portal.
							</p>
						</div>
					</div>

					{portalState === "error" && (
						<div className="flex items-center gap-2 rounded-lg bg-red-950/50 border border-red-900 px-4 py-3 text-sm text-red-300">
							<AlertCircle className="h-4 w-4 shrink-0" aria-hidden />
							Failed to open portal. Please try again.
						</div>
					)}

					<button
						type="button"
						onClick={openCustomerPortal}
						disabled={portalState === "loading"}
						className={cn(
							"inline-flex items-center gap-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-white font-medium text-sm px-5 py-2.5 transition-colors",
							portalState === "loading" && "opacity-60 cursor-not-allowed",
						)}
					>
						{portalState === "loading" ? (
							<>
								<Loader2 className="h-4 w-4 animate-spin" aria-hidden />
								Opening…
							</>
						) : (
							<>
								<CreditCard className="h-4 w-4" aria-hidden />
								Manage Billing
							</>
						)}
					</button>
				</div>

				{/* What's included */}
				<div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-6 space-y-4">
					<div className="flex items-start gap-4">
						<div className="mt-0.5 rounded-lg bg-zinc-800 p-2">
							<Calendar className="h-5 w-5 text-zinc-300" aria-hidden />
						</div>
						<div className="space-y-1">
							<h2 className="text-base font-semibold text-white">
								Plan Details
							</h2>
							<p className="text-zinc-400 text-sm">
								Your subscription renews automatically. Cancel any time with no
								penalty.
							</p>
						</div>
					</div>

					<ul className="space-y-2">
						{[
							"Unlimited Afrobeats track generation",
							"High-quality WAV + MP3 downloads",
							"Stem separation (vocals, drums, bass)",
							"Commercial usage rights",
							"Priority generation queue",
						].map((feature) => (
							<li
								key={feature}
								className="flex items-center gap-2.5 text-sm text-zinc-300"
							>
								<CheckCircle2
									className="h-4 w-4 shrink-0 text-emerald-400"
									aria-hidden
								/>
								{feature}
							</li>
						))}
					</ul>
				</div>

				<p className="text-center text-xs text-zinc-600">
					Need help?{" "}
					<Link href="/contact" className="text-zinc-400 hover:text-white transition-colors">
						Contact support
					</Link>
				</p>
			</div>
		</div>
	)
}
