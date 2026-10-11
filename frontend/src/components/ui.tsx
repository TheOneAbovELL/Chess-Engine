// Small, reusable UI primitives built on the design tokens in styles/index.css.

import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from "lucide-react";
import {
  Children,
  cloneElement,
  forwardRef,
  isValidElement,
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brass-500 text-ink-950 hover:bg-brass-400 active:bg-brass-600 shadow-[0_1px_0_rgb(255_255_255/0.25)_inset] disabled:bg-ink-600 disabled:text-ink-300",
  secondary: "border border-ink-600 bg-ink-800 text-ink-50 hover:border-ink-500 hover:bg-ink-750 active:bg-ink-700",
  ghost: "text-ink-200 hover:bg-ink-750 hover:text-ink-50 active:bg-ink-700",
  danger: "border border-q-blunder/50 bg-q-blunder/10 text-[#ff8f88] hover:bg-q-blunder/20 active:bg-q-blunder/30",
};
const SIZES: Record<Size, string> = {
  sm: "h-8 gap-1.5 px-2.5 text-xs",
  md: "h-9 gap-2 px-3.5 text-sm",
  lg: "h-11 gap-2 px-5 text-sm",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-lg font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-60",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

export function IconButton({
  label,
  className,
  children,
  active,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex size-9 items-center justify-center rounded-lg text-ink-200 transition-colors hover:bg-ink-750 hover:text-ink-50 active:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-40",
        active && "bg-ink-700 text-brass-300",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function Panel({ className, children, ...props }: React.HTMLAttributes<HTMLElement>) {
  return (
    <section className={cn("panel", className)} {...props}>
      {children}
    </section>
  );
}

export function PanelHeader({ title, subtitle, actions, icon }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; icon?: ReactNode }) {
  return (
    <header className="panel-header">
      <div className="flex min-w-0 items-center gap-2.5">
        {icon && <span className="text-brass-400">{icon}</span>}
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-ink-50">{title}</h2>
          {subtitle && <p className="truncate text-xs text-ink-300">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
    </header>
  );
}

export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: "neutral" | "good" | "warn" | "bad" | "brass" | "info"; className?: string }) {
  const tones = {
    neutral: "border-ink-600 bg-ink-800 text-ink-200",
    good: "border-q-best/40 bg-q-best/10 text-q-best",
    warn: "border-q-inaccuracy/40 bg-q-inaccuracy/10 text-q-inaccuracy",
    bad: "border-q-blunder/40 bg-q-blunder/10 text-[#ff8f88]",
    brass: "border-brass-600/50 bg-brass-500/10 text-brass-300",
    info: "border-sky-line/40 bg-sky-line/10 text-sky-line",
  };
  return <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium", tones[tone], className)}>{children}</span>;
}

export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return <Loader2 className={cn("size-4 animate-spin text-ink-300", className)} aria-label={label} role="status" />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4", className)} aria-hidden />;
}

export function ProgressBar({ value, max = 1, className, label }: { value: number; max?: number; className?: string; label?: string }) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div className={cn("h-2 w-full overflow-hidden rounded-full bg-ink-700", className)} role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-label={label}>
      <div className="h-full rounded-full bg-gradient-to-r from-brass-600 to-brass-400 transition-[width] duration-500" style={{ width: `${pct}%` }} />
    </div>
  );
}

export function EmptyState({ icon, title, children, actions }: { icon?: ReactNode; title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      {icon && <div className="mb-4 flex size-14 items-center justify-center rounded-2xl border border-ink-600 bg-ink-800 text-brass-400">{icon}</div>}
      <h3 className="text-base font-semibold text-ink-50">{title}</h3>
      {children && <div className="mt-2 max-w-md text-sm leading-relaxed text-ink-300">{children}</div>}
      {actions && <div className="mt-6 flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  );
}

export function Callout({ tone = "info", title, children, className }: { tone?: "info" | "warn" | "bad" | "good"; title?: ReactNode; children?: ReactNode; className?: string }) {
  const meta = {
    info: { icon: Info, cls: "border-sky-line/30 bg-sky-line/5 text-ink-100", iconCls: "text-sky-line" },
    warn: { icon: AlertTriangle, cls: "border-q-inaccuracy/30 bg-q-inaccuracy/5 text-ink-100", iconCls: "text-q-inaccuracy" },
    bad: { icon: XCircle, cls: "border-q-blunder/30 bg-q-blunder/5 text-ink-100", iconCls: "text-q-blunder" },
    good: { icon: CheckCircle2, cls: "border-q-best/30 bg-q-best/5 text-ink-100", iconCls: "text-q-best" },
  }[tone];
  const Icon = meta.icon;
  return (
    <div className={cn("flex gap-3 rounded-xl border p-3.5 text-sm", meta.cls, className)} role={tone === "bad" ? "alert" : undefined}>
      <Icon className={cn("mt-0.5 size-4 shrink-0", meta.iconCls)} aria-hidden />
      <div className="min-w-0 space-y-1">
        {title && <p className="font-medium text-ink-50">{title}</p>}
        {children && <div className="leading-relaxed text-ink-200">{children}</div>}
      </div>
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  size = "md",
}: {
  value: T;
  options: { value: T; label: ReactNode; disabled?: boolean }[];
  onChange: (value: T) => void;
  label: string;
  size?: "sm" | "md";
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-ink-600 bg-ink-900 p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          disabled={option.disabled}
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-md font-medium transition-colors disabled:opacity-40",
            size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm",
            value === option.value ? "bg-ink-700 text-ink-50 shadow-sm" : "text-ink-300 hover:text-ink-100",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

const NATIVE_CONTROLS = new Set(["input", "select", "textarea"]);

/** Labelled form field. A single native control child is linked to the label
 *  automatically (id/htmlFor, plus aria-describedby for the hint or error);
 *  any other content (e.g. a segmented control) is exposed as a labelled group. */
export function Field({ label, hint, error, children, htmlFor }: { label: ReactNode; hint?: ReactNode; error?: string | null; children: ReactNode; htmlFor?: string }) {
  const generated = useId();
  const labelId = `${generated}-label`;
  const noteId = `${generated}-note`;
  const note = error ?? hint;
  const child = Children.count(children) === 1 && isValidElement(children) ? children : null;
  const isNative = child !== null && typeof child.type === "string" && NATIVE_CONTROLS.has(child.type);
  const childProps = (child?.props ?? {}) as { id?: string };
  const controlId = htmlFor ?? (isNative ? (childProps.id ?? `${generated}-control`) : undefined);
  const content = isNative
    ? cloneElement(child as React.ReactElement<Record<string, unknown>>, {
        id: controlId,
        "aria-describedby": note ? noteId : undefined,
        "aria-invalid": error ? true : undefined,
      })
    : children;
  return (
    <div className="space-y-1.5">
      <label id={labelId} htmlFor={controlId} className="block text-xs font-medium text-ink-200">
        {label}
      </label>
      {isNative || htmlFor ? content : <div role="group" aria-labelledby={labelId}>{content}</div>}
      {error ? (
        <p id={noteId} className="text-xs text-[#ff8f88]">
          {error}
        </p>
      ) : hint ? (
        <p id={noteId} className="text-xs text-ink-400">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function Toggle({ checked, onChange, label, description }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string }) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <label htmlFor={id} className="text-sm text-ink-100">
          {label}
        </label>
        {description && <p className="text-xs text-ink-400">{description}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn("relative h-5 w-9 shrink-0 rounded-full transition-colors", checked ? "bg-brass-500" : "bg-ink-600")}
      >
        <span className={cn("absolute top-0.5 size-4 rounded-full bg-white shadow transition-transform", checked ? "translate-x-[18px]" : "translate-x-0.5")} />
      </button>
    </div>
  );
}

/** Accessible modal dialog using the native <dialog> element (focus handling, Esc). */
export function Dialog({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className="m-auto w-[min(92vw,480px)] rounded-2xl border border-ink-600 bg-ink-850 p-0 text-ink-100 shadow-2xl backdrop:bg-black/60 backdrop:backdrop-blur-sm"
    >
      {open && (
        <div>
          <div className="flex items-center justify-between border-b border-ink-700 px-5 py-4">
            <h2 className="text-base font-semibold text-ink-50">{title}</h2>
            <IconButton label="Close" onClick={onClose} className="size-8">
              <X className="size-4" />
            </IconButton>
          </div>
          <div className="px-5 py-4 text-sm text-ink-200">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-ink-700 px-5 py-3">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  danger,
  busy,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {message}
    </Dialog>
  );
}

export function Stat({ label, value, hint, accent }: { label: string; value: ReactNode; hint?: ReactNode; accent?: string }) {
  return (
    <div className="panel px-4 py-3.5">
      <p className="label">{label}</p>
      <p className="num mt-1.5 text-2xl font-semibold text-ink-50" style={accent ? { color: accent } : undefined}>
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-ink-400">{hint}</p>}
    </div>
  );
}

/** Win/draw/loss proportion bar. */
export function WdlBar({ wins, draws, losses, className }: { wins: number; draws: number; losses: number; className?: string }) {
  const total = wins + draws + losses;
  if (!total) return <div className={cn("h-2 rounded-full bg-ink-700", className)} />;
  const pct = (n: number) => `${(n / total) * 100}%`;
  return (
    <div className={cn("flex h-2 overflow-hidden rounded-full bg-ink-700", className)} role="img" aria-label={`${wins} wins, ${draws} draws, ${losses} losses`}>
      <div className="bg-win" style={{ width: pct(wins) }} />
      <div className="bg-draw/70" style={{ width: pct(draws) }} />
      <div className="bg-loss" style={{ width: pct(losses) }} />
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink-50 sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-ink-300">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
