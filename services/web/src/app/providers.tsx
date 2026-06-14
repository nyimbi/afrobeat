"use client"

import { useEffect, useRef } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ReactQueryDevtools } from "@tanstack/react-query-devtools"
import { SessionProvider } from "next-auth/react"
import { useAuthStore } from "@/store/auth"

const queryClient = new QueryClient({
	defaultOptions: {
		queries: {
			staleTime: 60_000,
			retry: 2,
			refetchOnWindowFocus: false,
		},
	},
})

function AuthHydrator({ children }: { children: React.ReactNode }) {
	const hydrate = useAuthStore((s) => s.hydrate)
	const hydrated = useRef(false)

	useEffect(() => {
		if (!hydrated.current) {
			hydrated.current = true
			hydrate()
		}
	}, [hydrate])

	return <>{children}</>
}

export function Providers({ children }: { children: React.ReactNode }) {
	return (
		<SessionProvider>
			<QueryClientProvider client={queryClient}>
				<AuthHydrator>{children}</AuthHydrator>
				{process.env.NODE_ENV === "development" && (
					<ReactQueryDevtools initialIsOpen={false} />
				)}
			</QueryClientProvider>
		</SessionProvider>
	)
}
