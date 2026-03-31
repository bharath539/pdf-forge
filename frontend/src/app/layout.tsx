import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "PDF Forge",
  description: "Learn bank statement formats and generate synthetic PDFs",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${inter.className} antialiased`}>
        <nav className="bg-slate-900 text-white">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-14">
              <Link href="/" className="text-lg font-semibold tracking-tight">
                PDF Forge
              </Link>
              <div className="flex items-center gap-6">
                <Link
                  href="/upload"
                  className="text-sm text-slate-300 hover:text-white transition-colors"
                >
                  Upload
                </Link>
                <Link
                  href="/formats"
                  className="text-sm text-slate-300 hover:text-white transition-colors"
                >
                  Formats
                </Link>
                <Link
                  href="/generate"
                  className="text-sm text-slate-300 hover:text-white transition-colors"
                >
                  Generate
                </Link>
              </div>
            </div>
          </div>
        </nav>
        <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {children}
        </main>
      </body>
    </html>
  );
}
