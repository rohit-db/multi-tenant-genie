import { cn } from "@/lib/utils";

/** SkyDesk brand mark — a rounded tile with a paper-plane glyph in brand color. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-lg shadow-sm",
        className,
      )}
      style={{
        background: "linear-gradient(135deg, var(--brand), var(--brand-strong))",
      }}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        className="h-[60%] w-[60%] text-white"
        aria-hidden
      >
        <path
          d="M3 11.5L21 3l-7 18-3.2-6.8L3 11.5z"
          fill="currentColor"
          fillOpacity="0.95"
        />
        <path
          d="M21 3l-9.2 11.2"
          stroke="var(--brand-strong)"
          strokeWidth="1.2"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}
