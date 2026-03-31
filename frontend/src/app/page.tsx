import Link from "next/link";

const cards = [
  {
    title: "Upload Statement",
    description:
      "Upload a bank statement PDF to learn its format automatically.",
    href: "/upload",
    icon: "\u2191",
  },
  {
    title: "Format Library",
    description: "Browse and manage learned statement format schemas.",
    href: "/formats",
    icon: "\u2261",
  },
  {
    title: "Generate PDFs",
    description:
      "Create synthetic bank statements from learned formats.",
    href: "/generate",
    icon: "\u2193",
  },
];

export default function HomePage() {
  return (
    <div>
      <div className="text-center mb-12 mt-8">
        <h1 className="text-3xl font-bold text-slate-900 mb-3">PDF Forge</h1>
        <p className="text-slate-500 max-w-xl mx-auto">
          Learn the structure of real bank statement PDFs, then generate
          realistic synthetic versions with fake data for testing and
          development.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 max-w-3xl mx-auto">
        {cards.map((card) => (
          <Link
            key={card.href}
            href={card.href}
            className="group block border border-slate-200 rounded-lg p-6 hover:border-blue-500 hover:shadow-md transition-all"
          >
            <div className="text-2xl text-blue-600 mb-3 font-mono">
              {card.icon}
            </div>
            <h2 className="text-lg font-semibold text-slate-900 mb-1 group-hover:text-blue-600 transition-colors">
              {card.title}
            </h2>
            <p className="text-sm text-slate-500">{card.description}</p>
            <div className="mt-4 text-sm text-blue-600 font-medium">
              Get started &rarr;
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
