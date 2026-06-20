import Link from "next/link"

export const metadata = {
	title: "Privacy Policy — Gbẹdu",
	description: "Read the Gbẹdu Privacy Policy.",
}

export default function PrivacyPage() {
	return (
		<div className="min-h-dvh px-4 py-16 relative">
			<div
				className="absolute inset-0"
				style={{ background: "radial-gradient(ellipse at 50% 0%, rgba(212,175,55,0.05) 0%, transparent 60%)" }}
			/>

			<div className="relative max-w-2xl mx-auto space-y-8">
				<nav className="text-sm text-zinc-500">
					<Link href="/" className="hover:text-afro-gold transition-colors">
						Gbẹdu
					</Link>{" "}
					/ Privacy Policy
				</nav>

				<div>
					<p className="text-afro-gold text-sm font-medium mb-1">Legal</p>
					<h1 className="font-display text-3xl font-bold text-zinc-100">Privacy Policy</h1>
					<p className="text-zinc-500 text-sm mt-1">
						Effective: 1 January 2025 &mdash; Last updated: 15 June 2026
					</p>
				</div>

				<div className="space-y-6 text-zinc-400 text-sm leading-relaxed">
					<section className="space-y-2">
						<h2 className="text-zinc-100 font-semibold text-base">1. Who we are</h2>
						<p>
							Gbẹdu (&ldquo;we&rdquo;, &ldquo;our&rdquo;, &ldquo;us&rdquo;) operates the music
							generation platform at gbedu.io. We are the data controller for personal data collected
							through the platform. Questions:{" "}
							<a href="mailto:privacy@gbedu.io" className="text-afro-gold hover:underline">
								privacy@gbedu.io
							</a>
							.
						</p>
					</section>

					<section className="space-y-2">
						<h2 className="text-zinc-100 font-semibold text-base">2. Data we collect</h2>
						<ul className="list-disc list-inside space-y-1 ml-2">
							<li>
								<strong className="text-zinc-300">Account data:</strong> name, email address, hashed
								password.
							</li>
							<li>
								<strong className="text-zinc-300">Payment data:</strong> billing address, last-four
								card digits (held by Stripe/Paystack — we never store full card numbers).
							</li>
							<li>
								<strong className="text-zinc-300">Usage data:</strong> generation prompts, track
								metadata, play counts, feature interactions.
							</li>
							<li>
								<strong className="text-zinc-300">Voice samples:</strong> audio files you upload for
								voice model training, retained only while your voice model is active.
							</li>
							<li>
								<strong className="text-zinc-300">Technical data:</strong> IP address, browser type,
								device identifiers, logs.
							</li>
						</ul>
					</section>

					<section className="space-y-2">
						<h2 className="text-zinc-100 font-semibold text-base">3. How we use your data</h2>
						<ul className="list-disc list-inside space-y-1 ml-2">
							<li>Provide, maintain, and improve the platform;</li>
							<li>Process payments and manage subscriptions;</li>
							<li>Send transactional emails (generation complete, receipts, security alerts);</li>
							<li>Detect and prevent fraud and abuse;</li>
							<li>Comply with legal obligations.</li>
						</ul>
						<p>
							We do <strong className="text-zinc-300">not</strong> sell your personal data to third
							parties or use your generated tracks to train our models without explicit opt-in consent.
						</p>
					</section>

					<section className="space-y-2">
						<h2 className="text-zinc-100 font-semibold text-base">4. Legal basis (GDPR)</h2>
						<p>
							We process your data on the bases of: (a) contract performance — to provide the service
							you signed up for; (b) legitimate interests — fraud prevention, security, analytics; (c)
							legal obligation — tax and financial record-keeping; (d) consent — marketing emails (you
							can withdraw at any time).
						</p>
					</section>

					<section className="space-y-2">
						<h2 className="text-zinc-100 font-semibold text-base">5. Data sharing</h2>
						<p>We share data only with:</p>
						<ul className="list-disc list-inside space-y-1 ml-2">
							<li>
								<strong className="text-zinc-300">Stripe / Paystack</strong> — payment processing;
							</li>
							<li>
								<strong className="text-zinc-300">Cloudflare R2</strong> — audio file storage;
							</li>
							<li>
								<strong className="text-zinc-300">Sentry</strong> — error monitoring (anonymised
								where possible);
							</li>
							<li>Authorities, where required by law.</li>
						</ul>
					</section>

					<section className="space-y-2">
						<h2 className="text-zinc-100 font-semibold text-base">6. Retention</h2>
						<p>
							Account data is retained while your account is active and for up to 90 days after
							deletion (to allow recovery). Payment records are retained for 7 years for accounting
							purposes. Voice sample audio files are deleted within 30 days of voice model deletion.
							Generated tracks are deleted within 30 days of account deletion unless downloaded.
						</p>
					</section>

					<section className="space-y-2">
						<h2 className="text-zinc-100 font-semibold text-base">7. Your rights</h2>
						<p>
							Under GDPR and equivalent laws you have the right to: access, rectify, erase, restrict
							processing of, and port your personal data. You may object to processing based on
							legitimate interests. To exercise these rights, email{" "}
							<a href="mailto:privacy@gbedu.io" className="text-afro-gold hover:underline">
								privacy@gbedu.io
							</a>
							. We will respond within 30 days.
						</p>
					</section>

					<section className="space-y-2">
						<h2 className="text-zinc-100 font-semibold text-base">8. Cookies</h2>
						<p>
							We use strictly necessary cookies (session management, CSRF protection) and optional
							analytics cookies. You can disable analytics cookies via your browser settings. We do not
							use advertising cookies.
						</p>
					</section>

					<section className="space-y-2">
						<h2 className="text-zinc-100 font-semibold text-base">9. Security</h2>
						<p>
							We use TLS in transit, AES-256 at rest, bcrypt password hashing, and JWT with short
							expiry. We conduct regular security reviews. Despite best efforts, no system is
							impenetrable — report vulnerabilities to{" "}
							<a href="mailto:security@gbedu.io" className="text-afro-gold hover:underline">
								security@gbedu.io
							</a>
							.
						</p>
					</section>

					<section className="space-y-2">
						<h2 className="text-zinc-100 font-semibold text-base">10. Changes</h2>
						<p>
							We will notify you of material changes by email or in-app banner at least 14 days before
							they take effect.
						</p>
					</section>

					<section className="space-y-2">
						<h2 className="text-zinc-100 font-semibold text-base">11. Complaints</h2>
						<p>
							You have the right to lodge a complaint with your local data protection authority. In the
							UK: the{" "}
							<a
								href="https://ico.org.uk"
								target="_blank"
								rel="noopener noreferrer"
								className="text-afro-gold hover:underline"
							>
								Information Commissioner&apos;s Office
							</a>
							.
						</p>
					</section>
				</div>

				<div className="border-t border-white/[0.06] pt-6 flex gap-4 text-xs text-zinc-500">
					<Link href="/terms" className="hover:text-afro-gold transition-colors">
						Terms of Service
					</Link>
					<Link href="/contact" className="hover:text-afro-gold transition-colors">
						Contact
					</Link>
				</div>
			</div>
		</div>
	)
}
