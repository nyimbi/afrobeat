import { withAuth } from "next-auth/middleware"
import { NextResponse } from "next/server"
import type { NextRequestWithAuth } from "next-auth/middleware"

export default withAuth(
	function middleware(req: NextRequestWithAuth) {
		// Token is valid — let through
		return NextResponse.next()
	},
	{
		callbacks: {
			authorized({ token }) {
				return token !== null
			},
		},
		pages: {
			signIn: "/login",
		},
	},
)

export const config = {
	// Protect all studio routes
	matcher: ["/studio/:path*", "/library/:path*", "/marketplace/:path*"],
}
