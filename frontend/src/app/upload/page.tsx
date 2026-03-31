"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import UploadDropzone from "@/components/UploadDropzone";
import SchemaPreview from "@/components/SchemaPreview";
import { learn, type LearnResponse } from "@/lib/api-client";

type PageState = "upload" | "processing" | "preview" | "saving" | "saved";

interface ProcessingStep {
  label: string;
  status: "pending" | "active" | "done";
}

const STEP_LABELS = [
  "Reading PDF...",
  "Extracting layout...",
  "Detecting patterns...",
  "Sanitizing...",
  "Complete!",
];

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function UploadPage() {
  const [pageState, setPageState] = useState<PageState>("upload");
  const [steps, setSteps] = useState<ProcessingStep[]>([]);
  const [result, setResult] = useState<LearnResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Save form state
  const [bankName, setBankName] = useState("");
  const [accountType, setAccountType] = useState("checking");
  const [displayName, setDisplayName] = useState("");
  const [savedFormatId, setSavedFormatId] = useState<string | null>(null);

  const simulateSteps = useCallback(
    (onDone: () => void) => {
      const initial: ProcessingStep[] = STEP_LABELS.map((label) => ({
        label,
        status: "pending" as const,
      }));
      setSteps(initial);

      let currentStep = 0;
      const advance = () => {
        if (currentStep >= STEP_LABELS.length) {
          onDone();
          return;
        }
        setSteps((prev) =>
          prev.map((s, i) => {
            if (i < currentStep) return { ...s, status: "done" as const };
            if (i === currentStep) return { ...s, status: "active" as const };
            return s;
          }),
        );
        currentStep++;
        setTimeout(advance, 600 + Math.random() * 400);
      };
      advance();
    },
    [],
  );

  const handleUpload = useCallback(
    async (file: File) => {
      setError(null);
      setPageState("processing");

      let learnResult: LearnResponse | null = null;
      let learnError: string | null = null;

      // Start API call
      const apiPromise = learn(file)
        .then((res) => {
          learnResult = res;
        })
        .catch((err) => {
          learnError =
            err instanceof Error ? err.message : "An unknown error occurred";
        });

      // Simulate steps in parallel
      await new Promise<void>((resolve) => {
        simulateSteps(() => {
          // After steps are done, wait for API if needed
          apiPromise.then(resolve);
        });
      });

      // Mark all steps done
      setSteps((prev) =>
        prev.map((s) => ({ ...s, status: "done" as const })),
      );

      if (learnError) {
        setError(learnError);
        setPageState("upload");
        return;
      }

      if (learnResult) {
        setResult(learnResult);
        setBankName((learnResult as LearnResponse).bank_name || "");
        setAccountType(
          (learnResult as LearnResponse).account_type || "checking",
        );
        setDisplayName((learnResult as LearnResponse).display_name || "");
        setPageState("preview");
      }
    },
    [simulateSteps],
  );

  const handleSave = useCallback(async () => {
    if (!result) return;

    setPageState("saving");
    setError(null);

    try {
      const res = await fetch(`${BASE_URL}/api/formats/${result.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bank_name: bankName,
          account_type: accountType,
          display_name: displayName,
        }),
      });

      if (!res.ok) {
        const body = await res.text().catch(() => "Unknown error");
        throw new Error(body);
      }

      setSavedFormatId(result.id);
      setPageState("saved");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to save format",
      );
      setPageState("preview");
    }
  }, [result, bankName, accountType, displayName]);

  const handleReset = useCallback(() => {
    setPageState("upload");
    setSteps([]);
    setResult(null);
    setError(null);
    setBankName("");
    setAccountType("checking");
    setDisplayName("");
    setSavedFormatId(null);
  }, []);

  return (
    <div className="max-w-3xl">
      {/* Page Header */}
      <h1 className="text-2xl font-bold text-slate-900 mb-2">
        Upload Statement
      </h1>
      <p className="text-slate-500 mb-6">
        Upload a real bank statement PDF. We&apos;ll learn the format and
        discard your data.
      </p>

      {/* Privacy Callout */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg px-5 py-4 mb-8">
        <div className="flex items-start gap-3">
          <svg
            className="w-5 h-5 text-blue-500 mt-0.5 flex-shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
            />
          </svg>
          <p className="text-sm text-blue-800">
            Your PDF is processed in memory only. No data is stored — only
            the structural format is retained.
          </p>
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-5 py-4 mb-6">
          <div className="flex items-start gap-3">
            <svg
              className="w-5 h-5 text-red-500 mt-0.5 flex-shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <p className="text-sm text-red-700">{error}</p>
          </div>
        </div>
      )}

      {/* Upload State */}
      {(pageState === "upload" || pageState === "processing") && (
        <UploadDropzone
          onUpload={handleUpload}
          disabled={pageState === "processing"}
          isUploading={pageState === "processing"}
        />
      )}

      {/* Processing Steps */}
      {steps.length > 0 &&
        (pageState === "processing" || pageState === "preview") && (
          <div className="mt-8 max-w-xl">
            <h3 className="text-sm font-semibold text-slate-700 mb-3">
              Processing Steps
            </h3>
            <div className="space-y-2">
              {steps.map((step, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 text-sm"
                >
                  {step.status === "pending" && (
                    <span className="w-5 h-5 rounded-full border-2 border-slate-200 flex-shrink-0" />
                  )}
                  {step.status === "active" && (
                    <svg
                      className="animate-spin w-5 h-5 text-blue-600 flex-shrink-0"
                      xmlns="http://www.w3.org/2000/svg"
                      fill="none"
                      viewBox="0 0 24 24"
                    >
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                      />
                    </svg>
                  )}
                  {step.status === "done" && (
                    <svg
                      className="w-5 h-5 text-green-500 flex-shrink-0"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                      />
                    </svg>
                  )}
                  <span
                    className={
                      step.status === "done"
                        ? "text-green-700"
                        : step.status === "active"
                          ? "text-blue-700 font-medium"
                          : "text-slate-400"
                    }
                  >
                    {step.label}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

      {/* Preview State */}
      {pageState === "preview" && result && (
        <div className="mt-10 space-y-8">
          <div>
            <h2 className="text-lg font-semibold text-slate-900 mb-1">
              Detected Format
            </h2>
            <p className="text-sm text-slate-500 mb-4">
              Here&apos;s what we learned from your statement. Review the
              structure, then save it to your format library.
            </p>
            <SchemaPreview schema={result.schema_json} />
          </div>

          {/* Save Form */}
          <div className="bg-white border border-slate-200 rounded-lg p-6 shadow-sm">
            <h3 className="text-sm font-semibold text-slate-700 mb-4">
              Save Format
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label
                  htmlFor="bankName"
                  className="block text-sm font-medium text-slate-600 mb-1.5"
                >
                  Bank Name
                </label>
                <input
                  id="bankName"
                  type="text"
                  value={bankName}
                  onChange={(e) => setBankName(e.target.value)}
                  placeholder="e.g. Chase, Bank of America"
                  className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              <div>
                <label
                  htmlFor="accountType"
                  className="block text-sm font-medium text-slate-600 mb-1.5"
                >
                  Account Type
                </label>
                <select
                  id="accountType"
                  value={accountType}
                  onChange={(e) => setAccountType(e.target.value)}
                  className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white"
                >
                  <option value="checking">Checking</option>
                  <option value="savings">Savings</option>
                  <option value="credit_card">Credit Card</option>
                </select>
              </div>

              <div className="sm:col-span-2">
                <label
                  htmlFor="displayName"
                  className="block text-sm font-medium text-slate-600 mb-1.5"
                >
                  Display Name
                </label>
                <input
                  id="displayName"
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="e.g. Chase Checking 2024"
                  className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
            </div>

            <button
              onClick={handleSave}
              disabled={!bankName.trim()}
              className={`mt-5 w-full py-2.5 rounded-lg text-sm font-medium transition-colors ${
                bankName.trim()
                  ? "bg-blue-600 text-white hover:bg-blue-700"
                  : "bg-slate-100 text-slate-400 cursor-not-allowed"
              }`}
            >
              Save to Format Library
            </button>
          </div>
        </div>
      )}

      {/* Saving State */}
      {pageState === "saving" && (
        <div className="mt-10 flex items-center justify-center py-12">
          <svg
            className="animate-spin h-8 w-8 text-blue-600"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
          <span className="ml-3 text-sm text-slate-600">
            Saving format...
          </span>
        </div>
      )}

      {/* Saved State */}
      {pageState === "saved" && (
        <div className="mt-10">
          <div className="bg-green-50 border border-green-200 rounded-lg px-6 py-8 text-center">
            <svg
              className="w-12 h-12 text-green-500 mx-auto mb-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <h3 className="text-lg font-semibold text-green-800 mb-2">
              Format Saved Successfully
            </h3>
            <p className="text-sm text-green-700 mb-6">
              Your bank statement format has been saved and is ready to use
              for generating synthetic PDFs.
            </p>
            <div className="flex items-center justify-center gap-4">
              <Link
                href={`/formats`}
                className="inline-flex items-center px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 transition-colors"
              >
                View in Format Library
              </Link>
              <button
                onClick={handleReset}
                className="inline-flex items-center px-4 py-2 border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50 transition-colors"
              >
                Upload Another
              </button>
            </div>
            {savedFormatId && (
              <p className="text-xs text-slate-400 mt-4">
                Format ID: {savedFormatId}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
