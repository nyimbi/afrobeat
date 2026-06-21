import type { Metadata, Viewport } from "next/types"
import { DM_Mono, Playfair_Display, Sora } from "next/font/google"
import "./globals.css"
import { Providers } from "./providers"

const sora = Sora({
	subsets: ["latin"],
	weight: ["300", "400", "500", "600", "700"],
	variable: "--font-sans",
	display: "swap",
})

const playfair = Playfair_Display({
	subsets: ["latin"],
	weight: ["400", "600", "700", "900"],
	style: ["normal", "italic"],
	variable: "--font-display",
	display: "swap",
})

const dmMono = DM_Mono({
	subsets: ["latin"],
	weight: ["400", "500"],
	style: ["normal", "italic"],
	variable: "--font-mono",
	display: "swap",
})

export const metadata: Metadata = {
	title: {
		default: "Gbẹdu — Make Your Afrobeats Song in 60 Seconds",
		template: "%s | Gbẹdu",
	},
	description:
		"AI-powered Afrobeats music generator. Create professional tracks in Afropop, Afrofusion, Alte, Amapiano and more — in English, Pidgin, Yoruba, Igbo, or a mix.",
	keywords: [
		"afrobeats",
		"afropop",
		"amapiano",
		"alte",
		"ai music",
		"music generator",
		"nigerian music",
		"african music",
		"gbedu",
	],
	authors: [{ name: "Gbẹdu" }],
	creator: "Gbẹdu",
	metadataBase: new URL(
		process.env.NEXT_PUBLIC_SITE_URL ?? "https://gbedu.app",
	),
	openGraph: {
		type: "website",
		locale: "en_US",
		url: "/",
		siteName: "Gbẹdu",
		title: "Gbẹdu — Make Your Afrobeats Song in 60 Seconds",
		description:
			"Create professional Afrobeats tracks with AI. Afropop, Amapiano, Alte and more.",
		images: [
			{
				url: "/og-image.png",
				width: 1200,
				height: 630,
				alt: "Gbẹdu — AI Afrobeats Generator",
			},
		],
	},
	twitter: {
		card: "summary_large_image",
		title: "Gbẹdu — Make Your Afrobeats Song in 60 Seconds",
		description:
			"Create professional Afrobeats tracks with AI. Afropop, Amapiano, Alte and more.",
		images: ["/og-image.png"],
		creator: "@gbeduapp",
	},
	manifest: "/manifest.json",
	icons: {
		icon: [
			{ url: "/favicon.ico" },
			{ url: "/icon-192.png", sizes: "192x192", type: "image/png" },
			{ url: "/icon-512.png", sizes: "512x512", type: "image/png" },
		],
		apple: [{ url: "/apple-touch-icon.png" }],
	},
}

export const viewport: Viewport = {
	themeColor: "#0A0A0F",
	colorScheme: "dark",
	width: "device-width",
	initialScale: 1,
	maximumScale: 1,
}

export default function RootLayout({
	children,
}: {
	children: React.ReactNode
}) {
	return (
		<html
			lang="en"
			className={`dark ${sora.variable} ${playfair.variable} ${dmMono.variable}`}
			suppressHydrationWarning
		>
			<body className="grain-overlay min-h-dvh bg-dark-bg-primary antialiased">
				<Providers>{children}</Providers>
			</body>
		</html>
	)
}
