import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Loader2 } from "lucide-react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-violet-600 text-white hover:bg-violet-500 disabled:bg-violet-600/40 disabled:text-white/50",
  secondary:
    "border border-zinc-700 bg-zinc-800/60 text-zinc-200 hover:bg-zinc-800 disabled:text-zinc-500 disabled:hover:bg-zinc-800/60",
  danger:
    "border border-red-900/60 bg-red-950/40 text-red-300 hover:bg-red-950/70 disabled:opacity-50",
  ghost: "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 disabled:opacity-50",
};

export function Button({
  variant = "secondary",
  loading = false,
  icon,
  children,
  className = "",
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  loading?: boolean;
  icon?: ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-zinc-500">
      <Loader2 className="h-4 w-4 animate-spin" />
      {label ?? "Loading…"}
    </div>
  );
}
