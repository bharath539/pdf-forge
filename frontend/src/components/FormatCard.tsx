import type { FormatSchema } from "@/lib/api-client";

interface FormatCardProps {
  format: FormatSchema;
  onClick?: (format: FormatSchema) => void;
  onDelete?: (format: FormatSchema) => void;
}

const accountTypeBadge: Record<string, string> = {
  checking:
    "bg-blue-100 text-blue-700",
  savings:
    "bg-green-100 text-green-700",
  credit_card:
    "bg-purple-100 text-purple-700",
};

function relativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffDay > 30) {
    return new Date(dateStr).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }
  if (diffDay >= 1) return `${diffDay} day${diffDay === 1 ? "" : "s"} ago`;
  if (diffHr >= 1) return `${diffHr} hour${diffHr === 1 ? "" : "s"} ago`;
  if (diffMin >= 1) return `${diffMin} minute${diffMin === 1 ? "" : "s"} ago`;
  return "just now";
}

function getSections(schema: Record<string, unknown>): unknown[] {
  if (Array.isArray(schema.sections)) return schema.sections;
  return [];
}

function getDescriptionPatterns(schema: Record<string, unknown>): unknown[] {
  if (Array.isArray(schema.description_patterns)) return schema.description_patterns;
  return [];
}

function getDisplayName(schema: Record<string, unknown>): string | null {
  if (typeof schema.display_name === "string") return schema.display_name;
  return null;
}

export default function FormatCard({ format, onClick, onDelete }: FormatCardProps) {
  const sections = getSections(format.schema_json ?? {});
  const patterns = getDescriptionPatterns(format.schema_json ?? {});
  const displayName = getDisplayName(format.schema_json ?? {});
  const badgeClass =
    accountTypeBadge[format.account_type] ?? "bg-slate-100 text-slate-700";
  const accountLabel = format.account_type.replace(/_/g, " ");

  return (
    <button
      onClick={() => onClick?.(format)}
      className="relative w-full text-left border border-slate-200 rounded-lg p-5 hover:border-blue-500 hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 group bg-white"
    >
      {/* Delete icon */}
      {onDelete && (
        <span
          role="button"
          tabIndex={0}
          onClick={(e) => {
            e.stopPropagation();
            onDelete(format);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.stopPropagation();
              onDelete(format);
            }
          }}
          className="absolute top-3 right-3 p-1.5 rounded-md text-slate-300 hover:text-red-500 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
          title="Delete format"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
            <path d="M10 11v6" />
            <path d="M14 11v6" />
            <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
          </svg>
        </span>
      )}

      {/* Bank name */}
      <h3 className="text-lg font-bold text-slate-900 group-hover:text-blue-600 transition-colors pr-8">
        {format.bank_name}
      </h3>

      {/* Account type badge */}
      <span
        className={`inline-block mt-1.5 px-2 py-0.5 rounded-full text-xs font-medium capitalize ${badgeClass}`}
      >
        {accountLabel}
      </span>

      {/* Display name */}
      {displayName && (
        <p className="text-sm text-slate-500 mt-2">{displayName}</p>
      )}

      {/* Meta row */}
      <div className="mt-3 pt-3 border-t border-slate-100 flex items-center gap-3 text-xs text-slate-400">
        <span>{sections.length} section{sections.length !== 1 ? "s" : ""}</span>
        <span>&middot;</span>
        <span>{patterns.length} pattern{patterns.length !== 1 ? "s" : ""}</span>
        <span>&middot;</span>
        <span>{relativeTime(format.created_at)}</span>
      </div>
    </button>
  );
}
