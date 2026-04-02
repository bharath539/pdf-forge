"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearApiKey, isAuthenticated } from "@/lib/api-client";

export default function NavBar() {
  const pathname = usePathname();
  const router = useRouter();
  const authed = isAuthenticated();

  // Don't show nav on login page
  if (pathname === "/login") return null;

  const handleLogout = () => {
    clearApiKey();
    router.push("/login");
  };

  return (
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
            {authed && (
              <button
                onClick={handleLogout}
                className="text-sm text-slate-400 hover:text-red-400 transition-colors"
              >
                Logout
              </button>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
