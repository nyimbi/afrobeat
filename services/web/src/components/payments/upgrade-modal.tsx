"use client"

import { useState } from "react"
import * as Dialog from "@radix-ui/react-dialog"
import { Check, X, Zap, Sparkles, Crown, Building2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"

interface Tier {
	id: "creator" | "pro" | "label"
	name: string
	price: { usd: number; ngn: number }
	icon: React.ReactNode
	color: string
	borderColor: string
	glowColor: string
	description: string
	features: string[]
	limits: { tracks: number | "unlimited"; downloads: string; stems: boolean }
}

const TIERS: Tier[] = [
	{
		id: "creator",
		name: "Creator",
		price: { usd: 9, ngn: 7_500 },
		icon: <Zap className="w-5 h-5" />,
		color: "text-amber-400",
		borderColor: "border-amber-500/40",
		glowColor: "shadow-amber-500/10",
		description: "For serious creators ready to build their sound",
		features: [
			"50 tracks per month",
			"MP3 downloads",
			"All sub-genres",
			"All languages",
			"Basic voice models",
			"Track library",
			"Share to social",
		],
		limits: { tracks: 50, downloads: "MP3", stems: false },
	},
	{
		id: "pro",
		name: "Pro",
		price: { usd: 29, ngn: 24_000 },
		icon: <Sparkles className="w-5 h-5" />,
		color: "text-purple-400",
		borderColor: "border-purple-500/40",
		glowColor: "shadow-purple-500/10",
		description: "For professional musicians and content creators",
		features: [
			"200 tracks per month",
			"WAV + MP3 downloads",
			"Stem separation",
			"Premium voice models",
			"BPM + key override",
			"Priority generation",
			"Commercial license",
			"API access",
		],
		limits: { tracks: 200, downloads: "WAV + MP3", stems: true },
	},
	{
		id: "label",
		name: "Label",
		price: { usd: 99, ngn: 82_000 },
		icon: <Crown className="w-5 h-5" />,
		color: "text-afro-gold",
		borderColor: "border-afro-gold/40",
		glowColor: "shadow-afro-gold/10",
		description: "For labels, studios, and production teams",
		features: [
			"Unlimited tracks",
			"All formats + stems",
			"Full commercial rights",
			"White-label export",
			"Team collaboration",
			"Dedicated support",
			"Custom voice training",
			"Bulk API access",
		],
		limits: { tracks: "unlimited", downloads: "All formats", stems: true },
	},
]

interface UpgradeModalProps {
	open: boolean
	onOpenChange: (open: boolean) => void
	defaultTier?: "creator" | "pro" | "label"
}

export function UpgradeModal({ open, onOpenChange, defaultTier = "pro" }: UpgradeModalProps) {
	const [selectedTier, setSelectedTier] = useState<"creator" | "pro" | "label">(defaultTier)
	const [currency, setCurrency] = useState<"usd" | "ngn">("usd")
	const [isLoading, setIsLoading] = useState(false)
	const [error, setError] = useState<string | null>(null)

	async function handleSubscribe(provider: "stripe" | "paystack") {
		setIsLoading(true)
		setError(null)
		try {
			const res = await api.payments.createCheckoutSession(selectedTier, provider)
			window.location.href = res.checkoutUrl
		} catch (err: unknown) {
			const message = err instanceof Error ? err.message : "Payment failed. Please try again."
			setError(message)
		} finally {
			setIsLoading(false)
		}
	}

	const tier = TIERS.find((t) => t.id === selectedTier)!

	return (
		<Dialog.Root open={open} onOpenChange={onOpenChange}>
			<Dialog.Portal>
				<Dialog.Overlay className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm animate-fade-in" />
				<Dialog.Content className="fixed inset-0 z-50 flex items-center justify-center p-4">
					<div className="relative w-full max-w-4xl max-h-[90dvh] overflow-y-auto rounded-2xl bg-dark-bg-secondary border border-white/[0.08] shadow-2xl animate-slide-up">
						{/* Close */}
						<Dialog.Close className="absolute top-4 right-4 z-10 w-8 h-8 rounded-full bg-white/[0.05] flex items-center justify-center text-zinc-400 hover:text-zinc-100 transition-colors">
							<X className="w-4 h-4" />
						</Dialog.Close>

						<div className="p-6 sm:p-8">
							{/* Header */}
							<div className="text-center mb-8">
								<p className="text-xs font-mono uppercase tracking-widest text-afro-gold/70 mb-2">
									Unlock your sound
								</p>
								<Dialog.Title className="font-display text-3xl sm:text-4xl font-bold text-zinc-100">
									Choose your plan
								</Dialog.Title>
								<p className="mt-2 text-sm text-zinc-500">
									Cancel anytime. No hidden fees.
								</p>

								{/* Currency toggle */}
								<div className="flex items-center justify-center gap-2 mt-4">
									<button
										onClick={() => setCurrency("usd")}
										className={cn(
											"px-3 py-1 rounded-full text-xs font-medium transition-all",
											currency === "usd"
												? "bg-afro-gold text-dark-bg-primary"
												: "text-zinc-500 hover:text-zinc-300",
										)}
									>
										USD
									</button>
									<button
										onClick={() => setCurrency("ngn")}
										className={cn(
											"px-3 py-1 rounded-full text-xs font-medium transition-all",
											currency === "ngn"
												? "bg-afro-gold text-dark-bg-primary"
												: "text-zinc-500 hover:text-zinc-300",
										)}
									>
										NGN ₦
									</button>
								</div>
							</div>

							{/* Free tier comparison row */}
							<div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
								{TIERS.map((t) => (
									<button
										key={t.id}
										onClick={() => setSelectedTier(t.id)}
										className={cn(
											"relative text-left rounded-xl border p-4 transition-all duration-200",
											selectedTier === t.id
												? cn("bg-dark-bg-elevated shadow-lg", t.borderColor, t.glowColor)
												: "border-white/[0.06] bg-dark-bg-tertiary/50 hover:border-white/[0.12]",
										)}
									>
										{t.id === "pro" && (
											<div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full bg-purple-500 text-[10px] font-bold uppercase tracking-wider text-white">
												Popular
											</div>
										)}

										<div className={cn("flex items-center gap-2 mb-2", t.color)}>
											{t.icon}
											<span className="font-semibold text-sm">{t.name}</span>
										</div>

										<div className="mb-1">
											<span className="text-2xl font-bold text-zinc-100">
												{currency === "usd"
													? `$${t.price.usd}`
													: `₦${t.price.ngn.toLocaleString()}`}
											</span>
											<span className="text-xs text-zinc-500 ml-1">/mo</span>
										</div>

										<p className="text-xs text-zinc-500 leading-snug">{t.description}</p>
									</button>
								))}
							</div>

							{/* Feature list for selected tier */}
							<div className="glass rounded-xl p-5 mb-6">
								<div className="flex items-center gap-2 mb-4">
									<span className={cn("font-semibold text-sm", tier.color)}>
										{tier.name} includes:
									</span>
								</div>
								<ul className="grid grid-cols-1 sm:grid-cols-2 gap-2">
									{tier.features.map((f) => (
										<li key={f} className="flex items-center gap-2 text-sm text-zinc-300">
											<Check className="w-3.5 h-3.5 text-afro-gold shrink-0" />
											{f}
										</li>
									))}
								</ul>
							</div>

							{/* Also includes free features */}
							<p className="text-xs text-zinc-600 text-center mb-6">
								All plans include everything in Free — plus the above.
							</p>

							{/* Error */}
							{error && (
								<p className="text-sm text-red-400 text-center mb-4">{error}</p>
							)}

							{/* Payment buttons */}
							<div className="flex flex-col sm:flex-row gap-3">
								<button
									onClick={() => handleSubscribe("stripe")}
									disabled={isLoading}
									className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl bg-afro-gold text-dark-bg-primary font-semibold hover:bg-afro-gold-300 transition-colors disabled:opacity-60"
								>
									{isLoading ? (
										<span className="inline-block w-4 h-4 border-2 border-dark-bg-primary/30 border-t-dark-bg-primary rounded-full animate-spin" />
									) : (
										"Pay with Card (Stripe)"
									)}
								</button>

								<button
									onClick={() => handleSubscribe("paystack")}
									disabled={isLoading}
									className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl bg-green-600 text-white font-semibold hover:bg-green-500 transition-colors disabled:opacity-60"
								>
									<Building2 className="w-4 h-4" />
									Pay with Paystack (₦)
								</button>
							</div>

							<p className="text-[10px] text-zinc-700 text-center mt-4">
								Secure payment. Powered by Stripe and Paystack. Cancel anytime from your account settings.
							</p>
						</div>
					</div>
				</Dialog.Content>
			</Dialog.Portal>
		</Dialog.Root>
	)
}
