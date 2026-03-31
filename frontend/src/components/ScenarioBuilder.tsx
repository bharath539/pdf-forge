"use client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ScenarioKey =
  | "single_month"
  | "multi_month"
  | "multi_account"
  | "partial"
  | "past_months"
  | "high_volume"
  | "minimal"
  | "zero_balance"
  | "negative_balance"
  | "multi_page"
  | "mixed_types"
  | "international";

export interface GenerationParams {
  startDate: string;
  months: number;
  txMin: number;
  txMax: number;
  openingBalance: string;
  includeEdgeCases: boolean;
  seed: string;
  currency: string;
}

interface ScenarioBuilderProps {
  selectedScenario: ScenarioKey | null;
  params: GenerationParams;
  onChange: (params: GenerationParams) => void;
}

// ---------------------------------------------------------------------------
// Defaults per scenario
// ---------------------------------------------------------------------------

export function defaultParamsForScenario(
  scenario: ScenarioKey | null,
): GenerationParams {
  const base: GenerationParams = {
    startDate: new Date().toISOString().slice(0, 10),
    months: 1,
    txMin: 15,
    txMax: 45,
    openingBalance: "5000.00",
    includeEdgeCases: false,
    seed: "",
    currency: "USD",
  };

  switch (scenario) {
    case "multi_month":
      return { ...base, months: 3 };
    case "multi_account":
      return { ...base, months: 1 };
    case "partial":
      return { ...base, txMin: 5, txMax: 12 };
    case "past_months":
      return {
        ...base,
        startDate: new Date(Date.now() - 180 * 86400000)
          .toISOString()
          .slice(0, 10),
        months: 3,
      };
    case "high_volume":
      return { ...base, txMin: 150, txMax: 300 };
    case "minimal":
      return { ...base, txMin: 1, txMax: 1 };
    case "zero_balance":
      return { ...base, openingBalance: "0.00" };
    case "negative_balance":
      return { ...base, openingBalance: "-250.00", includeEdgeCases: true };
    case "multi_page":
      return { ...base, txMin: 60, txMax: 120 };
    case "mixed_types":
      return { ...base, txMin: 20, txMax: 40, includeEdgeCases: true };
    case "international":
      return { ...base, currency: "EUR" };
    default:
      return base;
  }
}

// ---------------------------------------------------------------------------
// Currencies for international scenario
// ---------------------------------------------------------------------------

const CURRENCIES = [
  "USD",
  "EUR",
  "GBP",
  "CAD",
  "AUD",
  "JPY",
  "CHF",
  "CNY",
  "INR",
  "MXN",
  "BRL",
  "KRW",
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ScenarioBuilder({
  selectedScenario,
  params,
  onChange,
}: ScenarioBuilderProps) {
  if (!selectedScenario) {
    return (
      <div className="border border-slate-200 rounded-lg p-6 min-h-[200px] flex items-center justify-center">
        <p className="text-sm text-slate-400">
          Select a scenario above to configure parameters.
        </p>
      </div>
    );
  }

  const showMonths =
    selectedScenario === "multi_month" ||
    selectedScenario === "past_months" ||
    selectedScenario === "multi_account";

  const showCurrency = selectedScenario === "international";

  function set(patch: Partial<GenerationParams>) {
    onChange({ ...params, ...patch });
  }

  return (
    <div className="border border-slate-200 rounded-lg p-5 space-y-5">
      <h4 className="text-sm font-semibold text-slate-700">Parameters</h4>

      {/* Start date */}
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">
          Start Date
        </label>
        <input
          type="date"
          value={params.startDate}
          onChange={(e) => set({ startDate: e.target.value })}
          className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        />
      </div>

      {/* Number of months */}
      {showMonths && (
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">
            Number of Months
          </label>
          <input
            type="number"
            min={1}
            max={24}
            value={params.months}
            onChange={(e) =>
              set({ months: Math.max(1, parseInt(e.target.value) || 1) })
            }
            className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
          <p className="text-xs text-slate-400 mt-1">
            How many consecutive monthly statements to generate.
          </p>
        </div>
      )}

      {/* Transactions per month range */}
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">
          Transactions per Month:{" "}
          <span className="text-slate-900 font-semibold">
            {params.txMin} &ndash; {params.txMax}
          </span>
        </label>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400 w-8 text-right">
            {params.txMin}
          </span>
          <input
            type="range"
            min={1}
            max={500}
            value={params.txMin}
            onChange={(e) => {
              const v = parseInt(e.target.value);
              set({
                txMin: v,
                txMax: Math.max(v, params.txMax),
              });
            }}
            className="flex-1 accent-blue-600"
          />
        </div>
        <div className="flex items-center gap-3 mt-1">
          <span className="text-xs text-slate-400 w-8 text-right">
            {params.txMax}
          </span>
          <input
            type="range"
            min={1}
            max={500}
            value={params.txMax}
            onChange={(e) => {
              const v = parseInt(e.target.value);
              set({
                txMax: v,
                txMin: Math.min(v, params.txMin),
              });
            }}
            className="flex-1 accent-blue-600"
          />
        </div>
        <p className="text-xs text-slate-400 mt-1">
          Min and max transaction count per statement period.
        </p>
      </div>

      {/* Opening balance */}
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">
          Opening Balance
        </label>
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-slate-400">
            $
          </span>
          <input
            type="text"
            value={params.openingBalance}
            onChange={(e) => set({ openingBalance: e.target.value })}
            className="w-full border border-slate-300 rounded-md pl-7 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder="5000.00"
          />
        </div>
      </div>

      {/* Currency (international only) */}
      {showCurrency && (
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">
            Currency
          </label>
          <select
            value={params.currency}
            onChange={(e) => set({ currency: e.target.value })}
            className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            {CURRENCIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Include edge cases */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={params.includeEdgeCases}
          onClick={() => set({ includeEdgeCases: !params.includeEdgeCases })}
          className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
            params.includeEdgeCases ? "bg-blue-600" : "bg-slate-300"
          }`}
        >
          <span
            className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
              params.includeEdgeCases ? "translate-x-4" : "translate-x-0"
            }`}
          />
        </button>
        <label className="text-xs font-medium text-slate-600">
          Include edge cases
        </label>
      </div>

      {/* Seed */}
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">
          Seed{" "}
          <span className="font-normal text-slate-400">(optional)</span>
        </label>
        <input
          type="number"
          value={params.seed}
          onChange={(e) => set({ seed: e.target.value })}
          placeholder="Leave blank for random"
          className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        />
        <p className="text-xs text-slate-400 mt-1">
          Set a seed for reproducible output.
        </p>
      </div>
    </div>
  );
}
