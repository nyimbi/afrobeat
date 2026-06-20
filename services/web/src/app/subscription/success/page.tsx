"use client"

import Link from "next/link"
import { CheckCircle2, Music2 } from "lucide-react"

export default function SubscriptionSuccessPage() {
	return (
		<div className="min-h-dvh flex flex-col items-center justify-center bg-gradient-to-b from-zinc-950 to-zinc-900 px-4">
			<div className="w-full max-w-md text-center space-y-6">
				<div className="flex justify-center">
					<div className="relative">
						<Music2 className="h-12 w-12 text-emerald-400" aria-hidden />
						<CheckCircle2
							className="h-5 w-5 text-emerald-400 absolute -bottom-1 -right-1"
							aria-hidden
						/>
					</div>
				</div>

				<div className="space-y-2">
					<h1 className="text-2xl font-bold text-white tracking-tight">
						You&apos;re all set
					</h1>
					<p className="text-zinc-400 text-sm leading-relaxed">
						Your subscription is now active. Head to the studio and start
						making your first track.
					</p>
				</div>

				<div className="flex flex-col gap-3">
					<Link
						href="/studio"
						className="inline-flex items-center justify-center rounded-lg bg-emerald-500 hover:bg-emerald-400 text-white font-medium text-sm px-6 py-3 transition-colors"
					>
						Open Studio
					</Link>
					<Link
						href="/settings/billing"
						className="inline-flex items-center justify-center rounded-lg border border-zinc-700 hover:border-zinc-500 text-zinc-300 hover:text-white font-medium text-sm px-6 py-3 transition-colors"
					>
						View Billing
					</Link>
				</div>
			</div>
		</div>
	)
}
