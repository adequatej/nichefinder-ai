import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { HealthIndicator } from "@/components/health-indicator";
import { Nav } from "@/components/nav";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "NicheFinder AI",
  description: "Find low-competition YouTube niches before everyone else does.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <header className="flex items-center justify-between border-b px-6 py-3">
          <Link href="/" className="font-semibold">
            NicheFinder AI
          </Link>
          <Nav />
        </header>
        <div className="flex-1">{children}</div>
        <footer className="flex justify-end border-t px-6 py-2">
          <HealthIndicator />
        </footer>
      </body>
    </html>
  );
}
