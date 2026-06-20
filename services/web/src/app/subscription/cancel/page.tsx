"use client"

import Link from "next/link"
import { XCircle, ArrowLeft } from "lucide-react"

export default function SubscriptionCancelPage() {
	return (
		<div className="min-h-dvh flex flex-col items-center justify-center bg-gradient-to-b from-zinc-950 to-zinc-900 px-4">
			<div className="w-full max-w-md text-center space-y-6">
				<div className="flex justify-center">
					<XCircle className="h-12 w-12 text-zinc-500" aria-hidden />
				</div>

				<div className="space-y-2">
					<h1 className="text-2xl font-bold text-white tracking-tight">
						Checkout cancelled
					</h1>
					<p className="text-zinc-400 text-sm leading-relaxed">
						No charge was made. You can upgrade whenever you&apos;re ready —
						your free plan is still active.
					</p>
				</div>

				<div className="flex flex-col gap-3">
					<Link
						href="/upgrade"
						className="inline-flex items-center justify-center rounded-lg bg-zinc-800 hover:bg-zinc-700 text-white font-medium text-sm px-6 py-3 transition-colors"
					>
						See Plans
					</Link>
					<Link
						href="/studio"
						className="inline-flex items-center justify-center gap-2 text-zinc-400 hover:text-white text-sm transition-colors"
					>
						<ArrowLeft className="h-4 w-4" aria-hidden />
						Back to Studio
					</Link>
				</div>
			</div>
		</div>
	)
}
