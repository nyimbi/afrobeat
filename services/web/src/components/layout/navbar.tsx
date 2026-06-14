"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import * as DropdownMenu from "@radix-ui/react-dropdown-menu"
import * as Avatar from "@radix-ui/react-avatar"
import { Music2, Library, ShoppingBag, LogOut, Settings, CreditCard, User, Zap } from "lucide-react"
import { useAuthStore } from "@/store/auth"
import { cn } from "@/lib/utils"

const NAV_LINKS = [
	{ href: "/studio", label: "Studio", icon: Music2 },
	{ href: "/library", label: "Library", icon: Library },
	{ href: "/marketplace", label: "Marketplace", icon: ShoppingBag },
]

const TIER_LABELS: Record<string, string> = {
	free: "Free",
	creator: "Creator",
	pro: "Pro",
	label: "Label",
}

const TIER_COLORS: Record<string, string> = {
	free: "text-zinc-400 border-zinc-700",
	creator: "text-afro-gold-400 border-afro-gold-400/40",
	pro: "text-purple-400 border-purple-400/40",
	label: "text-emerald-400 border-emerald-400/40",
}

export function Navbar() {
	const pathname = usePathname()
	const { user, isAuthenticated, logout } = useAuthStore()

	return (
		<header className="fixed top-0 inset-x-0 z-50 h-16">
			{/* Blurred backdrop */}
			<div className="absolute inset-0 bg-dark-bg-primary/80 backdrop-blur-xl border-b border-white/[0.06]" />

			<nav className="relative h-full max-w-7xl mx-auto px-4 sm:px-6 flex items-center justify-between gap-4">
				{/* Logo */}
				<Link
					href="/"
					className="flex items-center gap-2.5 shrink-0 group"
					aria-label="Gbẹdu home"
				>
					<div className="relative w-8 h-8 rounded-lg bg-afro-gold/10 border border-afro-gold/30 flex items-center justify-center group-hover:bg-afro-gold/20 transition-colors">
						<Music2 className="w-4 h-4 text-afro-gold" />
						<div className="absolute inset-0 rounded-lg bg-afro-gold/5 blur-sm group-hover:bg-afro-gold/10 transition-colors" />
					</div>
					<span
						className="font-display text-xl font-bold tracking-tight"
						style={{ color: "#D4AF37", textShadow: "0 0 20px rgba(212,175,55,0.35)" }}
					>
						Gbẹdu
					</span>
				</Link>

				{/* Center nav links */}
				{isAuthenticated && (
					<div className="hidden sm:flex items-center gap-1">
						{NAV_LINKS.map(({ href, label, icon: Icon }) => {
							const active = pathname.startsWith(href)
							return (
								<Link
									key={href}
									href={href}
									className={cn(
										"flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-all",
										active
											? "bg-afro-gold/10 text-afro-gold"
											: "text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.05]",
									)}
								>
									<Icon className="w-3.5 h-3.5" />
									{label}
								</Link>
							)
						})}
					</div>
				)}

				{/* Right side */}
				<div className="flex items-center gap-3">
					{isAuthenticated && user ? (
						<>
							{/* Upgrade CTA for free users */}
							{user.subscriptionTier === "free" && (
								<Link
									href="/upgrade"
									className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold bg-afro-gold/10 text-afro-gold border border-afro-gold/30 hover:bg-afro-gold/20 transition-all"
								>
									<Zap className="w-3 h-3" />
									Upgrade
								</Link>
							)}

							{/* Tier badge */}
							<span
								className={cn(
									"hidden sm:inline-flex text-[10px] font-mono font-medium uppercase tracking-widest px-2 py-0.5 rounded border",
									TIER_COLORS[user.subscriptionTier] ?? TIER_COLORS.free,
								)}
							>
								{TIER_LABELS[user.subscriptionTier] ?? "Free"}
							</span>

							{/* User dropdown */}
							<DropdownMenu.Root>
								<DropdownMenu.Trigger asChild>
									<button
										className="flex items-center gap-2 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-afro-gold/60"
										aria-label="User menu"
									>
										<Avatar.Root className="w-8 h-8 rounded-full ring-1 ring-afro-gold/30 overflow-hidden">
											<Avatar.Image
												src={user.avatarUrl ?? undefined}
												alt={user.fullName}
												className="object-cover"
											/>
											<Avatar.Fallback className="w-full h-full flex items-center justify-center bg-afro-gold/10 text-afro-gold text-xs font-semibold">
												{user.fullName
													.split(" ")
													.map((n) => n[0])
													.slice(0, 2)
													.join("")
													.toUpperCase()}
											</Avatar.Fallback>
										</Avatar.Root>
									</button>
								</DropdownMenu.Trigger>

								<DropdownMenu.Portal>
									<DropdownMenu.Content
										className="z-50 min-w-48 rounded-xl bg-dark-bg-card border border-white/[0.08] p-1 shadow-2xl shadow-black/50 animate-slide-up"
										sideOffset={8}
										align="end"
									>
										{/* User info header */}
										<div className="px-3 py-2.5 border-b border-white/[0.06] mb-1">
											<p className="text-sm font-medium text-zinc-100 truncate">
												{user.fullName}
											</p>
											<p className="text-xs text-zinc-500 truncate">{user.email}</p>
										</div>

										{[
											{ href: "/profile", label: "Profile", icon: User },
											{ href: "/settings", label: "Settings", icon: Settings },
											{ href: "/billing", label: "Billing", icon: CreditCard },
										].map(({ href, label, icon: Icon }) => (
											<DropdownMenu.Item key={href} asChild>
												<Link
													href={href}
													className="flex items-center gap-2.5 px-3 py-2 text-sm text-zinc-300 hover:text-zinc-100 hover:bg-white/[0.05] rounded-lg transition-colors cursor-pointer outline-none"
												>
													<Icon className="w-4 h-4" />
													{label}
												</Link>
											</DropdownMenu.Item>
										))}

										<DropdownMenu.Separator className="my-1 border-t border-white/[0.06]" />

										<DropdownMenu.Item asChild>
											<button
												onClick={logout}
												className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors cursor-pointer outline-none"
											>
												<LogOut className="w-4 h-4" />
												Sign out
											</button>
										</DropdownMenu.Item>
									</DropdownMenu.Content>
								</DropdownMenu.Portal>
							</DropdownMenu.Root>
						</>
					) : (
						<div className="flex items-center gap-2">
							<Link
								href="/login"
								className="text-sm text-zinc-400 hover:text-zinc-200 transition-colors px-3 py-1.5"
							>
								Sign in
							</Link>
							<Link
								href="/register"
								className="text-sm font-semibold px-4 py-1.5 rounded-lg bg-afro-gold text-dark-bg-primary hover:bg-afro-gold-300 transition-colors"
							>
								Get started
							</Link>
						</div>
					)}
				</div>
			</nav>
		</header>
	)
}
