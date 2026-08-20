import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL || "https://evidensia.openai.site",
  ),
  title: "Evidensia — Autonomous Evidence Intelligence",
  description: "Plan investigations, challenge claims, and produce citation-grounded research reports.",
  openGraph: {
    title: "Evidensia",
    description: "Autonomous evidence intelligence",
    type: "website",
    images: [{ url: "/og.png", width: 1731, height: 909, alt: "Evidensia — Autonomous evidence intelligence" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Evidensia",
    description: "Autonomous evidence intelligence",
    images: ["/og.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
