import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono, Newsreader } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const serif = Newsreader({ subsets: ["latin"], variable: "--font-newsreader", display: "swap" });
const sans = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains", display: "swap" });

export const metadata: Metadata = {
  title: "RepoCompass",
  description: "Know a repo before you contribute.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: the dev-mode "1 Issue" is likely a browser extension adding
    // attributes to <html> or <body> before React loads (not confirmed); it covers only these tags
    <html
      lang="en"
      className={`${serif.variable} ${sans.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen font-sans antialiased" suppressHydrationWarning>
        <header className="border-b border-line">
          <nav className="mx-auto flex max-w-[1100px] items-baseline justify-between px-4 py-4 sm:px-8">
            <Link href="/" className="font-serif text-heading font-semibold text-ink no-underline">
              RepoCompass
            </Link>
            <Link href="/method" className="text-body text-muted hover:text-ink">
              Method
            </Link>
          </nav>
        </header>
        <main className="mx-auto max-w-[1100px] px-4 py-10 sm:px-8 sm:py-14">{children}</main>
        <footer className="border-t border-line">
          <div className="mx-auto flex max-w-[1100px] flex-wrap justify-between gap-2 px-4 py-6 text-small text-muted sm:px-8">
            <span>RepoCompass · built from public git history and pull requests</span>
            <Link href="/method" className="text-muted hover:text-ink">
              How the numbers are made
            </Link>
          </div>
        </footer>
      </body>
    </html>
  );
}
