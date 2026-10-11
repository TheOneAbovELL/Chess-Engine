import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";
import { useToasts } from "@/stores/toast";

export function Toaster() {
  const { toasts, dismiss } = useToasts();
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(92vw,380px)] flex-col gap-2" aria-live="polite" role="status">
      {toasts.map((t) => {
        const Icon = t.tone === "success" ? CheckCircle2 : t.tone === "error" ? XCircle : Info;
        return (
          <div
            key={t.id}
            className={cn(
              "pointer-events-auto flex gap-3 rounded-xl border bg-ink-800/95 p-3.5 shadow-2xl backdrop-blur",
              t.tone === "success" && "border-q-best/40",
              t.tone === "error" && "border-q-blunder/50",
              t.tone === "info" && "border-ink-600",
            )}
          >
            <Icon className={cn("mt-0.5 size-4 shrink-0", t.tone === "success" ? "text-q-best" : t.tone === "error" ? "text-q-blunder" : "text-sky-line")} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-ink-50">{t.title}</p>
              {t.message && <p className="mt-0.5 text-xs leading-relaxed text-ink-300">{t.message}</p>}
            </div>
            <button type="button" aria-label="Dismiss" onClick={() => dismiss(t.id)} className="text-ink-400 hover:text-ink-100">
              <X className="size-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
