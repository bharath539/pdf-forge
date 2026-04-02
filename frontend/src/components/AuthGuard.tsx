"use client";

import { useRouter, usePathname } from "next/navigation";
import { isAuthenticated } from "@/lib/api-client";

const PUBLIC_PATHS = ["/login"];

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  const isPublic = PUBLIC_PATHS.includes(pathname);
  const authed = isAuthenticated();

  if (!isPublic && !authed) {
    // Redirect on next tick to avoid calling router during render
    if (typeof window !== "undefined") {
      router.replace("/login");
    }
    return null;
  }

  return <>{children}</>;
}
