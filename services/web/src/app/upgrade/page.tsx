"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Check, Zap, Loader2 } from "lucide-react"
import { api, GbeduError } from "@/lib/api"
import { useAuthStore } from "@/store/auth"

const PLANS = [
	{
		id: "creator" as const,
		name: "Creator",
		price: "$9",
		period: "/mo",
		highlight: false,
		features: [
			"20 tracks per day",
			"320 kbps MP3 + WAV downloads",
			"Stem separation",
			"Marketplace selling",
			"Commercial licence on all tracks",
		],
	},
	{
		id: "pro" as const,
		name: "Pro",
		price: "$29",
		period: "/mo",
		highlight: true,
		features: [
			"100 tracks per day",
			"Lossless WAV + stems",
			"Custom voice model training",
			"Priority GPU queue",
			"API access",
		],
	},
	{
		id: "label" as const,
		name: "Label",
		price: "$99",
		period: "/mo",
		highlight: false,
		features: [
			"500 tracks per day",
			"White-label export",
			"Dedicated support + SLA",
			"Custom genre fine-tuning",
			"Team seats + shared library",
		],
	},
]

export default function UpgradePage() {
	const { user, isAuthenticated } = useAuthStore()
	const router = useRouter()
	const [loading, setLoading] = useState<string | null>(null)
	const [error, setError] = useState("")

	async function handleCheckout(tier: "creator" | "pro" | "label") {
		if (!isAuthenticated) {
			router.push("/login?redirect=/upgrade")
			return
		}
		setError("")
		setLoading(tier)
		try {
			const res = await api.payments.createCheckoutSession(tier, "stripe")
			if (res.checkoutUrl) {
				window.location.href = res.checkoutUrl
			}
		} catch (err) {
			setError(err instanceof GbeduError ? err.message : "Failed to start checkout. Please try again.")
			setLoading(null)
		}
	}

	return (
		<div className="min-h-dvh px-4 py-16 relative">
			<div
				className="absolute inset-0"
				style={{ background: "radial-gradient(ellipse at 50% 0%, rgba(212,175,55,0.08) 0%, transparent 65%)" }}
			/>

			<div className="relative max-w-5xl mx-auto space-y-10">
				<div className="text-center space-y-3">
					<div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-afro-gold/10 border border-afro-gold/30 text-afro-gold text-xs font-medium mb-2">
						<Zap className="w-3 h-3" />
						Upgrade your plan
					</div>
					<h1 className="font-display text-4xl font-bold text-zinc-100">
						Make more. Earn more.
					</h1>
					<p className="text-zinc-500 text-lg max-w-md mx-auto">
						Unlock unlimited generation, higher quality exports, and marketplace selling.
					</p>
					{user?.subscriptionTier && user.subscriptionTier !== "free" && (
						<p className="text-afro-gold text-sm">
							You&apos;re currently on the <strong>{user.subscriptionTier}</strong> plan.
						</p>
					)}
				</div>

				{error && (
					<p className="text-center text-red-400 text-sm" role="alert">
						{error}
					</p>
				)}

				<div className="grid grid-cols-1 md:grid-cols-3 gap-6">
					{PLANS.map((plan) => (
						<div
							key={plan.id}
							className={`relative rounded-2xl p-6 flex flex-col border transition-all ${
								plan.highlight
									? "bg-afro-gold/5 border-afro-gold/40 shadow-gold"
									: "glass border-white/[0.08]"
							}`}
						>
							{plan.highlight && (
								<div className="absolute -top-3 left-1/2 -translate-x-1/2">
									<span className="px-3 py-0.5 rounded-full bg-afro-gold text-dark-bg-primary text-xs font-semibold">
										Most popular
									</span>
								</div>
							)}

							<div className="mb-4">
								<h2 className="text-lg font-semibold text-zinc-100">{plan.name}</h2>
								<div className="flex items-baseline gap-1 mt-1">
									<span className="text-3xl font-bold text-zinc-100">{plan.price}</span>
									<span className="text-sm text-zinc-500">{plan.period}</span>
								</div>
							</div>

							<ul className="space-y-2.5 flex-1 mb-6">
								{plan.features.map((f) => (
									<li key={f} className="flex items-start gap-2 text-sm text-zinc-400">
										<Check className="w-3.5 h-3.5 text-afro-gold shrink-0 mt-0.5" />
										{f}
									</li>
								))}
							</ul>

							<button
								onClick={() => handleCheckout(plan.id)}
								disabled={loading !== null || user?.subscriptionTier === plan.id}
								className={`w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-60 cursor-pointer ${
									plan.highlight
										? "bg-afro-gold text-dark-bg-primary hover:bg-afro-gold-300 hover:shadow-gold"
										: "border border-white/[0.10] text-zinc-300 hover:border-white/[0.20] hover:text-zinc-100"
								}`}
							>
								{loading === plan.id ? (
									<>
										<Loader2 className="w-4 h-4 animate-spin" />
										Redirecting&hellip;
									</>
								) : user?.subscriptionTier === plan.id ? (
									"Current plan"
								) : (
									`Get ${plan.name}`
								)}
							</button>
						</div>
					))}
				</div>

				<p className="text-center text-xs text-zinc-600">
					All plans billed monthly. Cancel anytime. Prices in USD.
				</p>
			</div>
		</div>
	)
}
