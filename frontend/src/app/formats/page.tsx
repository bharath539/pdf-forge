"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { FormatSchema } from "@/lib/api-client";
import { getFormats, deleteFormat } from "@/lib/api-client";
import FormatCard from "@/components/FormatCard";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function schemaArray(schema: Record<string, unknown>, key: string): unknown[] {
  const val = schema[key];
  return Array.isArray(val) ? val : [];
}

function schemaString(schema: Record<string, unknown>, key: string): string | null {
  const val = schema[key];
  return typeof val === "string" ? val : null;
}

function schemaPageDimensions(
  schema: Record<string, unknown>,
): { width: number; height: number } | null {
  const pd = schema.page_dimensions;
  if (
    pd &&
    typeof pd === "object" &&
    !Array.isArray(pd) &&
    typeof (pd as Record<string, unknown>).width === "number" &&
    typeof (pd as Record<string, unknown>).height === "number"
  ) {
    return pd as { width: number; height: number };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Skeleton Card
// ---------------------------------------------------------------------------

function SkeletonCard() {
  return (
    <div className="border border-slate-200 rounded-lg p-5 animate-pulse">
      <div className="h-5 bg-slate-200 rounded w-2/3 mb-3" />
      <div className="h-4 bg-slate-100 rounded w-1/3 mb-4" />
      <div className="h-3 bg-slate-100 rounded w-1/2 mb-3" />
      <div className="border-t border-slate-100 pt-3 mt-3 flex gap-3">
        <div className="h-3 bg-slate-100 rounded w-16" />
        <div className="h-3 bg-slate-100 rounded w-16" />
        <div className="h-3 bg-slate-100 rounded w-20" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Confirmation Modal
// ---------------------------------------------------------------------------

function ConfirmDeleteModal({
  format,
  onConfirm,
  onCancel,
}: {
  format: FormatSchema;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onCancel}
      />
      {/* Dialog */}
      <div className="relative bg-white rounded-xl shadow-xl max-w-sm w-full mx-4 p-6">
        <h3 className="text-lg font-semibold text-slate-900 mb-2">
          Delete format?
        </h3>
        <p className="text-sm text-slate-500 mb-6">
          This will permanently delete the{" "}
          <span className="font-medium text-slate-700">
            {format.bank_name}
          </span>{" "}
          ({format.account_type.replace(/_/g, " ")}) format schema. This action
          cannot be undone.
        </p>
        <div className="flex items-center justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium text-slate-700 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail Panel
// ---------------------------------------------------------------------------

function DetailPanel({
  format,
  onClose,
  onDelete,
}: {
  format: FormatSchema;
  onClose: () => void;
  onDelete: (f: FormatSchema) => void;
}) {
  const router = useRouter();
  const sections = schemaArray(format.schema_json ?? {}, "sections");
  const patterns = schemaArray(format.schema_json ?? {}, "description_patterns");
  const fonts = schemaArray(format.schema_json ?? {}, "fonts");
  const displayName = schemaString(format.schema_json ?? {}, "display_name");
  const dims = schemaPageDimensions(format.schema_json ?? {});

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      {/* Panel */}
      <div className="relative bg-white w-full max-w-lg shadow-2xl overflow-y-auto animate-slide-in">
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between z-10">
          <h2 className="text-lg font-bold text-slate-900">Format Details</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="px-6 py-6 space-y-6">
          {/* Identity */}
          <div>
            <h3 className="text-2xl font-bold text-slate-900">
              {format.bank_name}
            </h3>
            <span
              className={`inline-block mt-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium capitalize ${
                format.account_type === "checking"
                  ? "bg-blue-100 text-blue-700"
                  : format.account_type === "savings"
                    ? "bg-green-100 text-green-700"
                    : format.account_type === "credit_card"
                      ? "bg-purple-100 text-purple-700"
                      : "bg-slate-100 text-slate-700"
              }`}
            >
              {format.account_type.replace(/_/g, " ")}
            </span>
            {displayName && (
              <p className="text-sm text-slate-500 mt-2">{displayName}</p>
            )}
          </div>

          {/* Timestamps */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs text-slate-400 mb-1">Learned</p>
              <p className="text-sm text-slate-700">
                {formatDate(format.created_at)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-400 mb-1">Format ID</p>
              <p className="text-sm text-slate-700 font-mono">
                {format.id.slice(0, 12)}...
              </p>
            </div>
          </div>

          {/* Page Dimensions */}
          {dims && (
            <div>
              <p className="text-xs text-slate-400 mb-1">Page Dimensions</p>
              <p className="text-sm text-slate-700">
                {dims.width} x {dims.height} pts
              </p>
            </div>
          )}

          {/* Fonts */}
          {fonts.length > 0 && (
            <div>
              <p className="text-xs text-slate-400 mb-2">
                Fonts ({fonts.length})
              </p>
              <div className="flex flex-wrap gap-1.5">
                {fonts.map((font, i) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 bg-slate-100 text-slate-600 rounded text-xs"
                  >
                    {String(font)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Sections */}
          {sections.length > 0 && (
            <div>
              <p className="text-xs text-slate-400 mb-2">
                Sections ({sections.length})
              </p>
              <ul className="space-y-1">
                {sections.map((section, i) => {
                  const name =
                    section &&
                    typeof section === "object" &&
                    "name" in (section as Record<string, unknown>)
                      ? String((section as Record<string, unknown>).name)
                      : `Section ${i + 1}`;
                  return (
                    <li
                      key={i}
                      className="text-sm text-slate-700 flex items-center gap-2"
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />
                      {name}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {/* Description Patterns */}
          {patterns.length > 0 && (
            <div>
              <p className="text-xs text-slate-400 mb-2">
                Description Patterns ({patterns.length})
              </p>
              <ul className="space-y-1">
                {patterns.map((p, i) => (
                  <li
                    key={i}
                    className="text-sm text-slate-600 font-mono bg-slate-50 rounded px-2 py-1 text-xs"
                  >
                    {String(p)}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Actions */}
          <div className="pt-4 border-t border-slate-200 flex gap-3">
            <button
              onClick={() =>
                router.push(`/generate?schema=${format.id}`)
              }
              className="flex-1 px-4 py-2.5 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors text-center"
            >
              Generate from this format
            </button>
            <button
              onClick={() => onDelete(format)}
              className="px-4 py-2.5 text-sm font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition-colors"
            >
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function FormatsPage() {
  const [formats, setFormats] = useState<FormatSchema[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedFormat, setSelectedFormat] = useState<FormatSchema | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<FormatSchema | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchFormats = useCallback(async () => {
    try {
      setError(null);
      const data = await getFormats();
      setFormats(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load formats",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchFormats();
  }, [fetchFormats]);

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteFormat(deleteTarget.id);
      // Close detail panel if deleting the currently viewed format
      if (selectedFormat?.id === deleteTarget.id) {
        setSelectedFormat(null);
      }
      setDeleteTarget(null);
      await fetchFormats();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to delete format",
      );
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-900 mb-2">
        Format Library
      </h1>
      <p className="text-slate-500 mb-8">
        Learned statement formats ready for synthetic PDF generation.
      </p>

      {/* Error */}
      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {/* Empty state */}
      {!loading && formats.length === 0 && !error && (
        <div className="border border-dashed border-slate-300 rounded-lg p-12 text-center">
          <div className="mx-auto w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mb-4">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="28"
              height="28"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-slate-400"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="12" y1="18" x2="12" y2="12" />
              <line x1="9" y1="15" x2="15" y2="15" />
            </svg>
          </div>
          <p className="text-slate-500 text-sm mb-4">
            No formats learned yet. Upload a statement to get started.
          </p>
          <Link
            href="/upload"
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
          >
            Upload a statement
          </Link>
        </div>
      )}

      {/* Format grid */}
      {!loading && formats.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {formats.map((format) => (
            <FormatCard
              key={format.id}
              format={format}
              onClick={setSelectedFormat}
              onDelete={setDeleteTarget}
            />
          ))}
        </div>
      )}

      {/* Detail panel */}
      {selectedFormat && (
        <DetailPanel
          format={selectedFormat}
          onClose={() => setSelectedFormat(null)}
          onDelete={(f) => {
            setDeleteTarget(f);
          }}
        />
      )}

      {/* Delete confirmation modal */}
      {deleteTarget && (
        <ConfirmDeleteModal
          format={deleteTarget}
          onConfirm={handleDelete}
          onCancel={() => !deleting && setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
