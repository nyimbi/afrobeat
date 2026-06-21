import { withAuth } from "next-auth/middleware"
import { NextResponse } from "next/server"

export default withAuth(
	function proxy() {
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
