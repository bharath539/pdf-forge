"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import {
  type FormatSchema,
  type GenerateParams,
  getFormats,
  generate,
  generatePreview,
  generateBatch,
} from "@/lib/api-client";
import ScenarioBuilder, {
  type ScenarioKey,
  type GenerationParams,
  defaultParamsForScenario,
} from "@/components/ScenarioBuilder";

// ---------------------------------------------------------------------------
// Scenario catalogue
// ---------------------------------------------------------------------------

interface ScenarioDef {
  key: ScenarioKey;
  name: string;
  description: string;
}

const SCENARIOS: ScenarioDef[] = [
  { key: "single_month", name: "Single Month", description: "Standard single statement" },
  { key: "multi_month", name: "Multi-Month", description: "Consecutive monthly statements" },
  { key: "multi_account", name: "Multi-Account", description: "Multiple account types" },
  { key: "partial", name: "Partial", description: "Mid-cycle / incomplete period" },
  { key: "past_months", name: "Past Months", description: "Backdated historical statements" },
  { key: "high_volume", name: "High Volume", description: "Hundreds of transactions" },
  { key: "minimal", name: "Minimal", description: "Single transaction" },
  { key: "zero_balance", name: "Zero Balance", description: "$0 opening and closing" },
  { key: "negative_balance", name: "Negative Balance", description: "Overdraft scenarios" },
  { key: "multi_page", name: "Multi-Page", description: "3+ pages of transactions" },
  { key: "mixed_types", name: "Mixed Types", description: "All transaction types" },
  { key: "international", name: "International", description: "Foreign currency" },
];

// ---------------------------------------------------------------------------
// Inner page (needs useSearchParams so must be wrapped in Suspense)
// ---------------------------------------------------------------------------

function GeneratePageInner() {
  // -- Formats --
  const searchParams = useSearchParams();
  const [formats, setFormats] = useState<FormatSchema[]>([]);
  const [selectedFormatId, setSelectedFormatId] = useState<string>("");
  const [formatsLoading, setFormatsLoading] = useState(true);
  const [formatsError, setFormatsError] = useState<string | null>(null);

  // -- Scenario + params --
  const [selectedScenario, setSelectedScenario] = useState<ScenarioKey | null>(null);
  const [params, setParams] = useState<GenerationParams>(defaultParamsForScenario(null));

  // -- Generation state --
  const [generating, setGenerating] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [batching, setBatching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ filename: string; size: string; url: string } | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // -- Load formats --
  useEffect(() => {
    let cancelled = false;
    setFormatsLoading(true);
    getFormats()
      .then((data) => {
        if (cancelled) return;
        setFormats(data);
        const preselect = searchParams.get("schema");
        if (preselect && data.some((f) => f.id === preselect)) {
          setSelectedFormatId(preselect);
        } else if (data.length > 0) {
          setSelectedFormatId(data[0].id);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setFormatsError(err instanceof Error ? err.message : "Failed to load formats");
      })
      .finally(() => {
        if (!cancelled) setFormatsLoading(false);
      });
    return () => { cancelled = true; };
  }, [searchParams]);

  // -- Scenario selection --
  const selectScenario = useCallback((key: ScenarioKey) => {
    setSelectedScenario(key);
    setParams(defaultParamsForScenario(key));
    setResult(null);
    setPreviewUrl(null);
    setError(null);
  }, []);

  // -- Build API payload --
  function buildPayload(): GenerateParams {
    return {
      schema_id: selectedFormatId,
      scenario: selectedScenario ?? "single_month",
      months: params.months,
      transactions_per_month: { min: params.txMin, max: params.txMax },
      start_date: params.startDate,
      opening_balance: params.openingBalance,
      include_edge_cases: params.includeEdgeCases,
      seed: params.seed ? parseInt(params.seed) : null,
    };
  }

  function triggerDownload(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // -- Handlers --
  async function handleGenerate() {
    if (!selectedFormatId || !selectedScenario) return;
    setGenerating(true);
    setError(null);
    setResult(null);
    try {
      const blob = await generate(buildPayload());
      const filename = `statement-${selectedScenario}-${Date.now()}.pdf`;
      const sizeKb = (blob.size / 1024).toFixed(1);
      setResult({
        filename,
        size: `${sizeKb} KB`,
        url: URL.createObjectURL(blob),
      });
      triggerDownload(blob, filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  }

  async function handlePreview() {
    if (!selectedFormatId || !selectedScenario) return;
    setPreviewing(true);
    setError(null);
    setPreviewUrl(null);
    try {
      const blob = await generatePreview(buildPayload());
      setPreviewUrl(URL.createObjectURL(blob));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview failed");
    } finally {
      setPreviewing(false);
    }
  }

  async function handleBatch() {
    if (!selectedFormatId) return;
    setBatching(true);
    setError(null);
    try {
      const blob = await generateBatch({
        schema_id: selectedFormatId,
        scenarios: SCENARIOS.map((s) => s.key),
        start_date: params.startDate,
        seed: params.seed ? parseInt(params.seed) : null,
      });
      const filename = `batch-${Date.now()}.zip`;
      const sizeMb = (blob.size / (1024 * 1024)).toFixed(1);
      setResult({
        filename,
        size: `${sizeMb} MB`,
        url: URL.createObjectURL(blob),
      });
      triggerDownload(blob, filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Batch generation failed");
    } finally {
      setBatching(false);
    }
  }

  const isReady = selectedFormatId && selectedScenario;
  const isBusy = generating || previewing || batching;

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-900 mb-1">
        Generate Synthetic PDFs
      </h1>
      <p className="text-slate-500 mb-8">
        Create realistic synthetic bank statements from learned formats.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* ---------------------------------------------------------------- */}
        {/* Left column - Configuration                                      */}
        {/* ---------------------------------------------------------------- */}
        <div className="lg:col-span-2 space-y-8">
          {/* Format selector */}
          <section>
            <label className="block text-sm font-semibold text-slate-700 mb-2">
              Format
            </label>
            {formatsLoading ? (
              <div className="border border-slate-200 rounded-lg p-4 text-sm text-slate-400 animate-pulse">
                Loading formats...
              </div>
            ) : formatsError ? (
              <div className="border border-red-200 bg-red-50 rounded-lg p-4 text-sm text-red-600">
                {formatsError}
              </div>
            ) : formats.length === 0 ? (
              <div className="border border-slate-200 rounded-lg p-4 text-sm text-slate-400">
                No formats available.{" "}
                <a href="/upload" className="text-blue-600 hover:underline">
                  Upload a PDF
                </a>{" "}
                to create one.
              </div>
            ) : (
              <select
                value={selectedFormatId}
                onChange={(e) => setSelectedFormatId(e.target.value)}
                className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                {formats.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.bank_name} &mdash; {f.account_type}
                  </option>
                ))}
              </select>
            )}
          </section>

          {/* Scenario selector */}
          <section>
            <h3 className="text-sm font-semibold text-slate-700 mb-3">
              Scenario
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
              {SCENARIOS.map((s) => {
                const active = selectedScenario === s.key;
                return (
                  <button
                    key={s.key}
                    onClick={() => selectScenario(s.key)}
                    className={`relative text-left border rounded-lg px-3 py-3 transition-all ${
                      active
                        ? "border-blue-500 bg-blue-50 shadow-sm"
                        : "border-slate-200 hover:border-slate-400"
                    }`}
                  >
                    {active && (
                      <span className="absolute top-2 right-2 flex h-4 w-4 items-center justify-center rounded-full bg-blue-600 text-white text-[10px]">
                        &#10003;
                      </span>
                    )}
                    <span
                      className={`block text-sm font-medium ${
                        active ? "text-blue-700" : "text-slate-800"
                      }`}
                    >
                      {s.name}
                    </span>
                    <span className="block text-xs text-slate-400 mt-0.5 leading-tight">
                      {s.description}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          {/* Parameter controls */}
          <section>
            <h3 className="text-sm font-semibold text-slate-700 mb-2">
              Configuration
            </h3>
            <ScenarioBuilder
              selectedScenario={selectedScenario}
              params={params}
              onChange={setParams}
            />
          </section>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Right column - Actions                                           */}
        {/* ---------------------------------------------------------------- */}
        <div className="space-y-4">
          <div className="sticky top-24 space-y-4">
            {/* Generate button */}
            <button
              disabled={!isReady || isBusy}
              onClick={handleGenerate}
              className="w-full flex items-center justify-center gap-2 bg-blue-600 text-white font-medium rounded-lg px-4 py-3 text-sm hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {generating ? (
                <>
                  <Spinner /> Generating...
                </>
              ) : (
                "Generate PDF"
              )}
            </button>

            {/* Preview button */}
            <button
              disabled={!isReady || isBusy}
              onClick={handlePreview}
              className="w-full flex items-center justify-center gap-2 border border-blue-600 text-blue-600 font-medium rounded-lg px-4 py-3 text-sm hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {previewing ? (
                <>
                  <Spinner /> Loading Preview...
                </>
              ) : (
                "Preview First Page"
              )}
            </button>

            {/* Batch button */}
            <button
              disabled={!selectedFormatId || isBusy}
              onClick={handleBatch}
              className="w-full flex items-center justify-center gap-2 border border-slate-300 text-slate-700 font-medium rounded-lg px-4 py-3 text-sm hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {batching ? (
                <>
                  <Spinner /> Generating Batch...
                </>
              ) : (
                "Batch Generate All Scenarios"
              )}
            </button>

            {/* Error */}
            {error && (
              <div className="border border-red-200 bg-red-50 rounded-lg p-3 text-sm text-red-600">
                {error}
              </div>
            )}

            {/* Result */}
            {result && (
              <div className="border border-green-200 bg-green-50 rounded-lg p-4">
                <p className="text-sm font-medium text-green-800">
                  Generated successfully
                </p>
                <p className="text-xs text-green-600 mt-1 truncate">
                  {result.filename}
                </p>
                <p className="text-xs text-green-600">{result.size}</p>
                {result.url && (
                  <a
                    href={result.url}
                    download={result.filename}
                    className="inline-block mt-2 text-xs font-medium text-green-700 hover:text-green-900 underline"
                  >
                    Download again
                  </a>
                )}
              </div>
            )}

            {/* Preview iframe */}
            {previewUrl && (
              <div className="border border-slate-200 rounded-lg overflow-hidden">
                <div className="bg-slate-100 px-3 py-2 flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-600">
                    Preview
                  </span>
                  <button
                    onClick={() => setPreviewUrl(null)}
                    className="text-xs text-slate-400 hover:text-slate-600"
                  >
                    Close
                  </button>
                </div>
                <object
                  data={previewUrl}
                  type="application/pdf"
                  className="w-full h-[400px]"
                >
                  <p className="p-4 text-sm text-slate-400">
                    Unable to display preview.{" "}
                    <a
                      href={previewUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline"
                    >
                      Open in new tab
                    </a>
                  </p>
                </object>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Spinner helper
// ---------------------------------------------------------------------------

function Spinner() {
  return (
    <svg
      className="animate-spin h-4 w-4"
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
  );
}

// ---------------------------------------------------------------------------
// Page export (with Suspense boundary for useSearchParams)
// ---------------------------------------------------------------------------

export default function GeneratePage() {
  return (
    <Suspense
      fallback={
        <div className="animate-pulse text-slate-400 text-sm">Loading...</div>
      }
    >
      <GeneratePageInner />
    </Suspense>
  );
}
