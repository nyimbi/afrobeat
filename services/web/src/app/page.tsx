"use client"

import { useState } from "react"
import Link from "next/link"
import type { Route } from "next"
import { Music2, Zap, Globe2, Download, ChevronRight, Check, ChevronDown } from "lucide-react"

// ---- Static demo tracks ----

const DEMO_TRACKS = [
	{
		id: "demo-1",
		title: "Lagos Midnight",
		genre: "Afropop",
		duration: "2:31",
		emoji: "🌃",
		color: "from-amber-900/60 to-orange-900/40",
	},
	{
		id: "demo-2",
		title: "Detty December",
		genre: "Amapiano",
		duration: "3:04",
		emoji: "🎉",
		color: "from-green-900/60 to-teal-900/40",
	},
	{
		id: "demo-3",
		title: "Jands Feeling",
		genre: "UK Afrobeats",
		duration: "2:47",
		emoji: "👑",
		color: "from-purple-900/60 to-indigo-900/40",
	},
]

const FEATURES = [
	{
		icon: <Zap className="w-5 h-5" />,
		title: "Generate",
		description:
			"Describe your vibe in plain language. Gbẹdu's AI composes original Afrobeats in under 60 seconds — rhythm, melody, vocals, mastered.",
	},
	{
		icon: <Globe2 className="w-5 h-5" />,
		title: "Customise",
		description:
			"Pick your sub-genre, language (Yoruba, Pidgin, Igbo, English, or a mix), energy level, and duration. Full creative control.",
	},
	{
		icon: <Download className="w-5 h-5" />,
		title: "Release",
		description:
			"Download studio-quality MP3 or WAV, grab individual stems, or share a 15-second preview card directly to social media.",
	},
]

const PRICING = [
	{
		name: "Free",
		price: "$0",
		period: "forever",
		description: "Explore the sound",
		features: ["5 tracks/month", "Preview clips", "Share cards", "All genres"],
		cta: "Start free",
		href: "/register",
		highlight: false,
	},
	{
		name: "Creator",
		price: "$9",
		period: "/mo",
		description: "Build your catalogue",
		features: ["50 tracks/month", "MP3 downloads", "Commercial license", "Priority queue"],
		cta: "Go Creator",
		href: "/register?plan=creator",
		highlight: false,
	},
	{
		name: "Pro",
		price: "$29",
		period: "/mo",
		description: "Professional quality",
		features: ["200 tracks/month", "WAV + stems", "All voice models", "API access"],
		cta: "Go Pro",
		href: "/register?plan=pro",
		highlight: true,
	},
	{
		name: "Label",
		price: "$99",
		period: "/mo",
		description: "For labels & studios",
		features: ["Unlimited tracks", "White-label export", "Team seats", "Custom AI training"],
		cta: "Contact us",
		href: "/contact",
		highlight: false,
	},
]

const FAQS = [
	{
		q: "Who owns the music Gbẹdu creates?",
		a: "You do. All tracks generated on Creator plan and above include a full commercial license — release on any platform, sell, sync, stream.",
	},
	{
		q: "What makes Gbẹdu different from other AI music tools?",
		a: "Gbẹdu is built exclusively for African music traditions. The model is trained on Afrobeats, Alte, Amapiano, and Afrofusion — not Western pop. It understands Yoruba, Igbo, and Pidgin linguistics natively.",
	},
	{
		q: "How long does generation take?",
		a: "30-second tracks generate in ~15s. A full 3-4 minute track takes 60-90 seconds. Pro users get priority queue access.",
	},
	{
		q: "Can I use Gbẹdu for commercial projects?",
		a: "Yes — Creator plan and above include commercial rights. Free plan tracks are for personal and demo use only.",
	},
	{
		q: "What's stem separation?",
		a: "Stems are the individual layers of your track — drums, bass, melody, vocals — exported as separate audio files. Available on Pro and Label plans.",
	},
]

// ---- Animated waveform component (pure CSS) ----

function HeroWaveform() {
	const bars = Array.from({ length: 48 })
	return (
		<div className="flex items-end justify-center gap-[3px] h-24 w-full max-w-lg mx-auto">
			{bars.map((_, i) => {
				// Create organic waveform shape
				const baseH = 15 + Math.sin(i * 0.38) * 25 + Math.cos(i * 0.19) * 18 + Math.sin(i * 0.71) * 12
				const delay = (i * 0.07) % 1.4
				const duration = 0.8 + (i % 7) * 0.1
				return (
					<span
						key={i}
						className="rounded-full bg-afro-gold"
						style={{
							width: "4px",
							height: `${Math.max(8, baseH)}%`,
							opacity: 0.4 + 0.6 * (i % 2 === 0 ? 1 : 0.6),
							animation: `waveform ${duration}s ease-in-out infinite`,
							animationDelay: `${delay}s`,
						}}
					/>
				)
			})}
		</div>
	)
}

// ---- Page ----

export default function LandingPage() {
	const [openFaq, setOpenFaq] = useState<number | null>(null)

	return (
		<div className="min-h-dvh bg-dark-bg-primary text-zinc-100 overflow-x-hidden">
			{/* ===== NAVBAR ===== */}
			<header className="fixed top-0 inset-x-0 z-50 h-16">
				<div className="absolute inset-0 bg-dark-bg-primary/80 backdrop-blur-xl border-b border-white/[0.06]" />
				<div className="relative h-full max-w-7xl mx-auto px-4 sm:px-6 flex items-center justify-between">
					<div className="flex items-center gap-2.5">
						<div className="w-8 h-8 rounded-lg bg-afro-gold/10 border border-afro-gold/30 flex items-center justify-center">
							<Music2 className="w-4 h-4 text-afro-gold" />
						</div>
						<span
							className="font-display text-xl font-bold"
							style={{ color: "#D4AF37", textShadow: "0 0 20px rgba(212,175,55,0.35)" }}
						>
							Gbẹdu
						</span>
					</div>

					<div className="hidden sm:flex items-center gap-6">
						<a href="#features" className="text-sm text-zinc-500 hover:text-zinc-200 transition-colors">Features</a>
						<a href="#pricing" className="text-sm text-zinc-500 hover:text-zinc-200 transition-colors">Pricing</a>
						<a href="#faq" className="text-sm text-zinc-500 hover:text-zinc-200 transition-colors">FAQ</a>
					</div>

					<div className="flex items-center gap-2">
						<Link href="/login" className="text-sm text-zinc-400 hover:text-zinc-200 px-3 py-1.5 transition-colors">
							Sign in
						</Link>
						<Link
							href="/register"
							className="text-sm font-semibold px-4 py-1.5 rounded-lg bg-afro-gold text-dark-bg-primary hover:bg-afro-gold-300 transition-colors"
						>
							Get started free
						</Link>
					</div>
				</div>
			</header>

			{/* ===== HERO ===== */}
			<section className="relative min-h-dvh flex flex-col items-center justify-center px-4 pt-24 pb-16 text-center overflow-hidden">
				{/* Background: radial afro-gold glow + adire pattern */}
				<div className="absolute inset-0 bg-[radial-gradient(ellipse_70%_60%_at_50%_0%,rgba(212,175,55,0.12),transparent_70%)]" />
				<div className="absolute inset-0 adire-texture" />

				{/* Decorative rings */}
				<div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full border border-afro-gold/[0.04] pointer-events-none" />
				<div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[900px] h-[900px] rounded-full border border-afro-gold/[0.025] pointer-events-none" />
				<div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[1200px] h-[1200px] rounded-full border border-afro-gold/[0.015] pointer-events-none" />

				{/* Badge */}
				<div
					className="relative inline-flex items-center gap-2 px-3 py-1 rounded-full border border-afro-gold/30 bg-afro-gold/8 text-xs font-medium text-afro-gold mb-6"
					style={{ animationDelay: "0s" }}
				>
					<span className="relative flex w-2 h-2">
						<span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-afro-gold opacity-75" />
						<span className="relative inline-flex rounded-full h-2 w-2 bg-afro-gold" />
					</span>
					Now in early access — 4,200+ creators
				</div>

				{/* Headline */}
				<h1
					className="relative font-display text-5xl sm:text-6xl md:text-7xl lg:text-8xl font-black leading-[0.95] tracking-tight max-w-4xl"
					style={{ textShadow: "0 0 80px rgba(212,175,55,0.08)" }}
				>
					Make Your{" "}
					<span
						className="text-gold-glow"
						style={{ color: "#D4AF37" }}
					>
						Afrobeats
					</span>
					<br />
					Song in{" "}
					<span className="italic font-black" style={{ color: "#D4AF37" }}>
						60 Seconds
					</span>
				</h1>

				<p className="relative mt-6 text-base sm:text-lg text-zinc-500 max-w-xl leading-relaxed">
					Describe your vibe. Gbẹdu&apos;s AI composes original Afropop, Amapiano, Alte and more —
					in English, Yoruba, Pidgin, Igbo, or a mix. No instruments. No studio.
				</p>

				{/* CTAs */}
				<div className="relative flex flex-col sm:flex-row items-center gap-3 mt-8">
					<Link
						href="/register"
						className="flex items-center gap-2 px-8 py-4 rounded-xl bg-afro-gold text-dark-bg-primary font-bold text-base hover:bg-afro-gold-300 transition-all shadow-lg shadow-afro-gold/20 animate-pulse-gold"
					>
						Start Creating Free
						<ChevronRight className="w-4 h-4" />
					</Link>
					<a
						href="#demo"
						className="flex items-center gap-2 px-6 py-4 rounded-xl border border-white/[0.10] text-zinc-400 text-base hover:text-zinc-200 hover:border-white/[0.2] transition-all"
					>
						<span className="text-lg">▶</span>
						Hear a demo
					</a>
				</div>

				{/* Living waveform */}
				<div className="relative mt-16 w-full max-w-2xl">
					<HeroWaveform />
					<div className="absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-dark-bg-primary to-transparent" />
				</div>
			</section>

			{/* ===== DEMO TRACKS ===== */}
			<section id="demo" className="py-20 px-4 sm:px-6">
				<div className="max-w-4xl mx-auto">
					<div className="text-center mb-10">
						<p className="text-[10px] font-mono uppercase tracking-widest text-afro-gold/60 mb-2">
							Hear what&apos;s possible
						</p>
						<h2 className="font-display text-3xl sm:text-4xl font-bold text-zinc-100">
							AI-generated. Fully original.
						</h2>
					</div>

					<div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
						{DEMO_TRACKS.map((track) => (
							<div
								key={track.id}
								className={`rounded-2xl bg-gradient-to-br ${track.color} border border-white/[0.08] p-5 space-y-4 relative overflow-hidden group hover:border-afro-gold/20 transition-all duration-300`}
							>
								<div className="absolute inset-0 adire-texture opacity-20" />
								<div className="relative flex items-center justify-between">
									<span className="text-3xl">{track.emoji}</span>
									<button className="w-9 h-9 rounded-full bg-white/10 border border-white/20 flex items-center justify-center text-white/80 hover:bg-afro-gold/20 hover:text-afro-gold hover:border-afro-gold/40 transition-all">
										<Music2 className="w-4 h-4" />
									</button>
								</div>
								<div className="relative">
									<p className="font-display text-lg font-bold text-zinc-100">{track.title}</p>
									<p className="text-xs text-zinc-500 mt-0.5">
										{track.genre} · {track.duration}
									</p>
								</div>
								{/* Static waveform preview */}
								<div className="relative flex items-end gap-px h-8">
									{Array.from({ length: 32 }).map((_, i) => (
										<span
											key={i}
											className="flex-1 rounded-sm bg-white/20 group-hover:bg-afro-gold/40 transition-colors duration-500"
											style={{
												height: `${20 + Math.sin(i * 0.6 + track.id.charCodeAt(5)) * 35 + Math.cos(i * 0.3) * 20}%`,
											}}
										/>
									))}
								</div>
							</div>
						))}
					</div>
				</div>
			</section>

			{/* ===== FEATURES ===== */}
			<section id="features" className="py-20 px-4 sm:px-6 relative">
				<div className="absolute inset-0 bg-[radial-gradient(ellipse_50%_40%_at_50%_50%,rgba(107,33,168,0.06),transparent)]" />
				<div className="max-w-5xl mx-auto">
					<div className="text-center mb-14">
						<p className="text-[10px] font-mono uppercase tracking-widest text-afro-gold/60 mb-2">
							How it works
						</p>
						<h2 className="font-display text-3xl sm:text-4xl font-bold text-zinc-100">
							Three steps to your next hit
						</h2>
					</div>

					<div className="grid grid-cols-1 md:grid-cols-3 gap-6">
						{FEATURES.map((f, i) => (
							<div
								key={f.title}
								className="relative rounded-2xl glass border border-white/[0.07] p-6 space-y-4 group hover:border-afro-gold/15 transition-all duration-300"
							>
								{/* Step number */}
								<div className="absolute top-4 right-4 font-mono text-5xl font-bold text-white/[0.03] leading-none select-none">
									{i + 1}
								</div>
								<div className="w-10 h-10 rounded-xl bg-afro-gold/10 border border-afro-gold/20 flex items-center justify-center text-afro-gold group-hover:bg-afro-gold/15 transition-colors">
									{f.icon}
								</div>
								<div>
									<h3 className="font-display text-lg font-bold text-zinc-100">{f.title}</h3>
									<p className="text-sm text-zinc-500 mt-1.5 leading-relaxed">{f.description}</p>
								</div>
							</div>
						))}
					</div>
				</div>
			</section>

			{/* ===== SOCIAL PROOF ===== */}
			<section className="py-12 px-4 border-y border-white/[0.05]">
				<div className="max-w-5xl mx-auto">
					<div className="flex flex-col sm:flex-row items-center justify-center gap-8 sm:gap-16 text-center">
						{[
							{ value: "4,200+", label: "Creators" },
							{ value: "180K+", label: "Tracks generated" },
							{ value: "16+", label: "Sub-genres" },
							{ value: "< 60s", label: "Average generation" },
						].map((stat) => (
							<div key={stat.label}>
								<div
									className="font-display text-3xl sm:text-4xl font-black"
									style={{ color: "#D4AF37", textShadow: "0 0 30px rgba(212,175,55,0.2)" }}
								>
									{stat.value}
								</div>
								<div className="text-xs text-zinc-600 uppercase tracking-widest mt-1 font-mono">
									{stat.label}
								</div>
							</div>
						))}
					</div>
				</div>
			</section>

			{/* ===== PRICING ===== */}
			<section id="pricing" className="py-20 px-4 sm:px-6 relative">
				<div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_50%_at_50%_50%,rgba(212,175,55,0.04),transparent)]" />
				<div className="max-w-6xl mx-auto">
					<div className="text-center mb-14">
						<p className="text-[10px] font-mono uppercase tracking-widest text-afro-gold/60 mb-2">
							Simple, transparent
						</p>
						<h2 className="font-display text-3xl sm:text-4xl font-bold text-zinc-100">
							Pricing
						</h2>
						<p className="text-sm text-zinc-600 mt-2">Cancel anytime. No hidden fees.</p>
					</div>

					<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
						{PRICING.map((plan) => (
							<div
								key={plan.name}
								className={`relative rounded-2xl border p-5 flex flex-col transition-all duration-300 ${
									plan.highlight
										? "border-afro-gold/40 bg-afro-gold/5 shadow-xl shadow-afro-gold/5"
										: "border-white/[0.07] bg-dark-bg-card hover:border-white/[0.14]"
								}`}
							>
								{plan.highlight && (
									<div className="absolute -top-3.5 left-1/2 -translate-x-1/2 px-4 py-1 rounded-full bg-afro-gold text-dark-bg-primary text-[10px] font-bold uppercase tracking-wider">
										Most popular
									</div>
								)}

								<div className="mb-4">
									<h3 className="font-display text-lg font-bold text-zinc-100">{plan.name}</h3>
									<p className="text-xs text-zinc-600 mt-0.5">{plan.description}</p>
								</div>

								<div className="mb-5">
									<span className="text-3xl font-black text-zinc-100">{plan.price}</span>
									<span className="text-sm text-zinc-600 ml-1">{plan.period}</span>
								</div>

								<ul className="space-y-2 flex-1 mb-6">
									{plan.features.map((f) => (
										<li key={f} className="flex items-start gap-2 text-sm text-zinc-400">
											<Check className="w-3.5 h-3.5 text-afro-gold shrink-0 mt-0.5" />
											{f}
										</li>
									))}
								</ul>

								<Link
									href={plan.href as Route<string>}
									className={`block text-center py-2.5 rounded-xl text-sm font-semibold transition-all ${
										plan.highlight
											? "bg-afro-gold text-dark-bg-primary hover:bg-afro-gold-300"
											: "border border-white/[0.10] text-zinc-300 hover:border-white/[0.20] hover:text-zinc-100"
									}`}
								>
									{plan.cta}
								</Link>
							</div>
						))}
					</div>
				</div>
			</section>

			{/* ===== FAQ ===== */}
			<section id="faq" className="py-20 px-4 sm:px-6">
				<div className="max-w-2xl mx-auto">
					<div className="text-center mb-12">
						<p className="text-[10px] font-mono uppercase tracking-widest text-afro-gold/60 mb-2">
							Got questions
						</p>
						<h2 className="font-display text-3xl sm:text-4xl font-bold text-zinc-100">FAQ</h2>
					</div>

					<div className="space-y-2">
						{FAQS.map((faq, i) => {
							const isOpen = openFaq === i
							return (
								<div
									key={faq.q}
									className="rounded-xl glass border border-white/[0.07] overflow-hidden transition-all hover:border-white/[0.12]"
								>
									<button
										onClick={() => setOpenFaq(isOpen ? null : i)}
										className="w-full flex items-center justify-between gap-4 p-5 text-left"
										aria-expanded={isOpen}
									>
										<h3 className="font-semibold text-zinc-200 text-sm leading-snug">{faq.q}</h3>
										<ChevronDown
											className={`w-4 h-4 text-zinc-500 shrink-0 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
										/>
									</button>
									{isOpen && (
										<div className="px-5 pb-5 animate-fade-in">
											<p className="text-sm text-zinc-500 leading-relaxed">{faq.a}</p>
										</div>
									)}
								</div>
							)
						})}
					</div>
				</div>
			</section>

			{/* ===== CTA FOOTER BANNER ===== */}
			<section className="py-24 px-4 relative overflow-hidden">
				<div className="absolute inset-0 bg-[radial-gradient(ellipse_70%_70%_at_50%_50%,rgba(212,175,55,0.08),transparent)]" />
				<div className="absolute inset-0 adire-texture opacity-30" />
				<div className="relative max-w-2xl mx-auto text-center space-y-6">
					<h2 className="font-display text-4xl sm:text-5xl font-black text-zinc-100 leading-tight">
						Your sound is{" "}
						<span style={{ color: "#D4AF37" }}>waiting</span>.
					</h2>
					<p className="text-zinc-500 text-base">
						Join thousands of artists, producers, and creators making original Afrobeats with Gbẹdu.
					</p>
					<Link
						href="/register"
						className="inline-flex items-center gap-2 px-10 py-4 rounded-xl bg-afro-gold text-dark-bg-primary font-bold text-base hover:bg-afro-gold-300 transition-all shadow-xl shadow-afro-gold/20 animate-pulse-gold"
					>
						Start Creating — It&apos;s Free
						<ChevronRight className="w-5 h-5" />
					</Link>
				</div>
			</section>

			{/* ===== FOOTER ===== */}
			<footer className="border-t border-white/[0.06] py-10 px-4 sm:px-6">
				<div className="max-w-7xl mx-auto">
					<div className="flex flex-col sm:flex-row items-center justify-between gap-6">
						<div className="flex items-center gap-2">
							<div className="w-7 h-7 rounded-lg bg-afro-gold/10 border border-afro-gold/30 flex items-center justify-center">
								<Music2 className="w-3.5 h-3.5 text-afro-gold" />
							</div>
							<span className="font-display font-bold" style={{ color: "#D4AF37" }}>
								Gbẹdu
							</span>
						</div>

						<div className="flex flex-wrap justify-center gap-x-6 gap-y-2 text-xs text-zinc-600">
							<Link href="/terms" className="hover:text-zinc-400 transition-colors">Terms</Link>
							<Link href="/privacy" className="hover:text-zinc-400 transition-colors">Privacy</Link>
							<Link href="/contact" className="hover:text-zinc-400 transition-colors">Contact</Link>
							<a href="https://twitter.com/gbeduapp" className="hover:text-zinc-400 transition-colors">Twitter</a>
							<a href="https://instagram.com/gbeduapp" className="hover:text-zinc-400 transition-colors">Instagram</a>
						</div>

						<p className="text-xs text-zinc-700">
							© {new Date().getFullYear()} Gbẹdu. All rights reserved.
						</p>
					</div>
				</div>
			</footer>
		</div>
	)
}
