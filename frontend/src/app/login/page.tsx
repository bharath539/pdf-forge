"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { setApiKey } from "@/lib/api-client";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      // Validate the password by calling the formats endpoint
      const res = await fetch(`${BASE_URL}/api/formats`, {
        headers: { "X-API-Key": password },
      });

      if (res.status === 401) {
        setError("Invalid password. Please try again.");
        setLoading(false);
        return;
      }

      if (!res.ok) {
        setError("Server error. Please try again later.");
        setLoading(false);
        return;
      }

      // Password is correct — store it and redirect
      setApiKey(password);
      router.push("/upload");
    } catch {
      setError("Cannot connect to server. Please try again later.");
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="max-w-md w-full bg-white rounded-lg shadow-md p-8">
        <h1 className="text-2xl font-bold text-center mb-2">PDF Forge</h1>
        <p className="text-gray-500 text-center mb-6">
          Enter the access password to continue
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Access password"
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              autoFocus
              required
            />
          </div>

          {error && (
            <p className="text-red-600 text-sm text-center">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || !password}
            className="w-full py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "Verifying..." : "Sign In"}
          </button>
        </form>
      </div>
    </div>
  );
}
