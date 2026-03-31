"use client";

interface SchemaPreviewProps {
  schema: Record<string, unknown>;
}

interface FontInfo {
  role?: string;
  family?: string;
  size?: number;
  weight?: string;
}

interface SectionInfo {
  name?: string;
  y_start?: number;
  y_end?: number;
  type?: string;
}

interface ColumnInfo {
  name?: string;
  x?: number;
  width?: number;
  alignment?: string;
}

interface PatternInfo {
  pattern?: string;
  type?: string;
  examples?: string[];
}

function getRoleColor(role: string): string {
  const colors: Record<string, string> = {
    title: "bg-purple-100 text-purple-700 border-purple-200",
    header: "bg-blue-100 text-blue-700 border-blue-200",
    body: "bg-slate-100 text-slate-700 border-slate-200",
    label: "bg-amber-100 text-amber-700 border-amber-200",
    amount: "bg-green-100 text-green-700 border-green-200",
    date: "bg-cyan-100 text-cyan-700 border-cyan-200",
    footer: "bg-gray-100 text-gray-600 border-gray-200",
  };
  return colors[role] || "bg-slate-100 text-slate-600 border-slate-200";
}

function getSectionColor(type: string): string {
  const colors: Record<string, string> = {
    header: "border-l-blue-500",
    summary: "border-l-amber-500",
    transactions: "border-l-green-500",
    footer: "border-l-gray-400",
  };
  return colors[type] || "border-l-slate-300";
}

export default function SchemaPreview({ schema }: SchemaPreviewProps) {
  const pageLayout = schema.page_layout as
    | Record<string, unknown>
    | undefined;
  const fonts = (schema.fonts || []) as FontInfo[];
  const sections = (schema.sections || []) as SectionInfo[];
  const columns = (schema.transaction_columns ||
    schema.columns ||
    []) as ColumnInfo[];
  const patterns = (schema.description_patterns ||
    schema.patterns ||
    []) as PatternInfo[];
  const margins = pageLayout?.margins as
    | Record<string, number>
    | undefined;

  return (
    <div className="space-y-6">
      {/* Page Layout */}
      {pageLayout && (
        <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
          <h4 className="text-sm font-semibold text-slate-700 mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-blue-500" />
            Page Layout
          </h4>
          <div className="flex gap-6 items-start">
            {/* Mini page diagram */}
            <div className="relative w-28 h-36 border-2 border-slate-300 rounded bg-white flex-shrink-0">
              {margins && (
                <>
                  <div
                    className="absolute top-0 left-0 right-0 bg-blue-50 border-b border-dashed border-blue-300"
                    style={{
                      height: `${Math.min(((margins.top || 0) / 792) * 100, 20)}%`,
                    }}
                  />
                  <div
                    className="absolute bottom-0 left-0 right-0 bg-blue-50 border-t border-dashed border-blue-300"
                    style={{
                      height: `${Math.min(((margins.bottom || 0) / 792) * 100, 20)}%`,
                    }}
                  />
                  <div
                    className="absolute top-0 left-0 bottom-0 bg-blue-50 border-r border-dashed border-blue-300"
                    style={{
                      width: `${Math.min(((margins.left || 0) / 612) * 100, 20)}%`,
                    }}
                  />
                  <div
                    className="absolute top-0 right-0 bottom-0 bg-blue-50 border-l border-dashed border-blue-300"
                    style={{
                      width: `${Math.min(((margins.right || 0) / 612) * 100, 20)}%`,
                    }}
                  />
                </>
              )}
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-[9px] text-slate-400">Content</span>
              </div>
            </div>

            {/* Page info */}
            <div className="text-sm space-y-1.5 text-slate-600">
              {pageLayout.width != null && pageLayout.height != null && (
                <div>
                  <span className="text-slate-400">Size:</span>{" "}
                  {String(pageLayout.width)} x {String(pageLayout.height)} pt
                </div>
              )}
              {margins && (
                <div>
                  <span className="text-slate-400">Margins:</span>{" "}
                  {margins.top ?? "?"} / {margins.right ?? "?"} /{" "}
                  {margins.bottom ?? "?"} / {margins.left ?? "?"} pt
                </div>
              )}
              {pageLayout.orientation != null && (
                <div>
                  <span className="text-slate-400">Orientation:</span>{" "}
                  {String(pageLayout.orientation)}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Fonts Detected */}
      {fonts.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
          <h4 className="text-sm font-semibold text-slate-700 mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-purple-500" />
            Fonts Detected
            <span className="text-xs font-normal text-slate-400">
              ({fonts.length})
            </span>
          </h4>
          <div className="flex flex-wrap gap-2">
            {fonts.map((font, i) => (
              <div
                key={i}
                className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-medium ${getRoleColor(font.role || "body")}`}
              >
                <span className="font-semibold">
                  {font.role || "unknown"}
                </span>
                <span className="opacity-60">|</span>
                <span>{font.family || "Unknown"}</span>
                {font.size && (
                  <>
                    <span className="opacity-60">|</span>
                    <span>{font.size}pt</span>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sections Found */}
      {sections.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
          <h4 className="text-sm font-semibold text-slate-700 mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-500" />
            Sections Found
            <span className="text-xs font-normal text-slate-400">
              ({sections.length})
            </span>
          </h4>
          <div className="space-y-2">
            {sections.map((section, i) => (
              <div
                key={i}
                className={`border-l-4 ${getSectionColor(section.type || section.name || "")} bg-slate-50 rounded-r px-4 py-2.5 flex items-center justify-between`}
              >
                <div className="flex items-center gap-3">
                  <span className="text-sm font-medium text-slate-700 capitalize">
                    {section.name || section.type || `Section ${i + 1}`}
                  </span>
                  {section.type && section.type !== section.name && (
                    <span className="text-xs text-slate-400 bg-white px-2 py-0.5 rounded border border-slate-200">
                      {section.type}
                    </span>
                  )}
                </div>
                {(section.y_start !== undefined ||
                  section.y_end !== undefined) && (
                  <span className="text-xs text-slate-400 font-mono">
                    y: {section.y_start ?? "?"}
                    {section.y_end !== undefined ? ` - ${section.y_end}` : ""}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Transaction Table Columns */}
      {columns.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
          <h4 className="text-sm font-semibold text-slate-700 mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-500" />
            Transaction Table
            <span className="text-xs font-normal text-slate-400">
              ({columns.length} columns)
            </span>
          </h4>
          <div className="overflow-x-auto">
            <div className="inline-flex border border-slate-200 rounded-lg overflow-hidden">
              {columns.map((col, i) => (
                <div
                  key={i}
                  className={`px-4 py-2.5 text-center ${i > 0 ? "border-l border-slate-200" : ""}`}
                >
                  <div className="text-xs font-semibold text-slate-700">
                    {col.name || `Col ${i + 1}`}
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5 space-x-1">
                    {col.alignment && <span>{col.alignment}</span>}
                    {col.width && <span>w:{col.width}</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Patterns Detected */}
      {patterns.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
          <h4 className="text-sm font-semibold text-slate-700 mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-red-400" />
            Patterns Detected
            <span className="text-xs font-normal text-slate-400">
              ({patterns.length})
            </span>
          </h4>
          <div className="space-y-2">
            {patterns.map((pat, i) => (
              <div
                key={i}
                className="bg-slate-50 rounded px-4 py-2.5 border border-slate-100"
              >
                <div className="flex items-center gap-2 mb-1">
                  {pat.type && (
                    <span className="text-xs px-2 py-0.5 bg-slate-200 text-slate-600 rounded font-medium">
                      {pat.type}
                    </span>
                  )}
                  <code className="text-xs text-slate-600 font-mono">
                    {pat.pattern || "—"}
                  </code>
                </div>
                {pat.examples && pat.examples.length > 0 && (
                  <div className="text-[10px] text-slate-400 mt-1">
                    e.g. {pat.examples.slice(0, 3).join(", ")}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Fallback if schema is mostly empty */}
      {!pageLayout &&
        fonts.length === 0 &&
        sections.length === 0 &&
        columns.length === 0 &&
        patterns.length === 0 && (
          <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
            <h4 className="text-sm font-semibold text-slate-700 mb-3">
              Raw Schema
            </h4>
            <pre className="text-xs text-slate-600 bg-slate-50 rounded p-4 overflow-x-auto whitespace-pre-wrap">
              {JSON.stringify(schema, null, 2)}
            </pre>
          </div>
        )}
    </div>
  );
}
