import type { Metadata, Viewport } from "next"
import "./globals.css"
import { Providers } from "./providers"

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
		<html lang="en" className="dark" suppressHydrationWarning>
			<head>
				<link rel="preconnect" href="https://fonts.googleapis.com" />
				<link
					rel="preconnect"
					href="https://fonts.gstatic.com"
					crossOrigin="anonymous"
				/>
				<link
					href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;0,900;1,400;1,700&family=DM+Mono:ital,wght@0,400;0,500;1,400&family=Sora:wght@300;400;500;600;700&display=swap"
					rel="stylesheet"
				/>
			</head>
			<body className="grain-overlay min-h-dvh bg-dark-bg-primary antialiased">
				<Providers>{children}</Providers>
			</body>
		</html>
	)
}
