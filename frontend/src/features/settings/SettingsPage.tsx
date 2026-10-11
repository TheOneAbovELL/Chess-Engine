import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, Database, HardDriveDownload, Info, Palette, Save, SlidersHorizontal, Trash2, Users } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Callout, Dialog, Field, PageHeader, Panel, PanelHeader, Skeleton, Toggle } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatBytes, plural } from "@/lib/format";
import { BOARD_THEMES, usePreferences, type BoardThemeId } from "@/stores/preferences";
import { toast } from "@/stores/toast";
import type { AppConfig, ClassificationThresholds, EngineSettings } from "@/types/api";

export default function SettingsPage() {
  return (
    <div>
      <PageHeader title="Settings" description="Engine resources, review thresholds, appearance and your local data." />
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="space-y-5">
          <EnginesPanel />
          <EngineSettingsPanel />
        </div>
        <div className="space-y-5">
          <ThresholdsPanel />
          <AppearancePanel />
          <AccountsPanel />
          <DataPanel />
          <AboutPanel />
        </div>
      </div>
    </div>
  );
}

function EnginesPanel() {
  const engines = useQuery({ queryKey: ["engines"], queryFn: api.engines });
  const stockfish = engines.data?.find((e) => e.id === "stockfish");
  return (
    <Panel id="engines">
      <PanelHeader title="Engines" icon={<Cpu className="size-4" />} />
      <div className="space-y-3 p-4">
        {engines.isPending && <Skeleton className="h-16" />}
        {engines.data?.map((e) => (
          <div key={e.id} className="flex items-center justify-between rounded-lg border border-ink-700 bg-ink-900 px-3 py-2.5">
            <div>
              <p className="text-sm font-medium text-ink-50">{e.display_name}</p>
              <p className="text-xs text-ink-400">{e.name ?? (e.available ? "Installed · starts on first use" : "Not found")}</p>
            </div>
            <Badge tone={e.available ? "good" : "warn"}>{e.available ? "available" : "missing"}</Badge>
          </div>
        ))}
        {stockfish && !stockfish.available && (
          <Callout tone="warn" title="Stockfish is not installed">
            <ol className="list-decimal space-y-1 pl-4">
              <li>
                In PowerShell, from the ChessLab folder run <code className="num text-ink-50">.\scripts\install_stockfish.ps1</code> (downloads the official release from GitHub), <em>or</em>
              </li>
              <li>
                download Stockfish from stockfishchess.org yourself and set <code className="num text-ink-50">CHESSLAB_STOCKFISH_PATH</code> in the <code className="num">.env</code> file.
              </li>
              <li>Restart the backend.</li>
            </ol>
            <p className="mt-2">For security, the engine path can only be set on the server, never from this page.</p>
          </Callout>
        )}
      </div>
    </Panel>
  );
}

function EngineSettingsPanel() {
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });
  const current = useQuery({ queryKey: ["settings", "engine"], queryFn: api.engineSettings });
  if (!current.data || !config.data) return <Skeleton className="h-96" />;
  // Keyed by the saved values: the form re-initialises whenever they change.
  return <EngineSettingsForm key={JSON.stringify(current.data)} initial={current.data} limits={config.data.limits} />;
}

function EngineSettingsForm({ initial, limits }: { initial: EngineSettings; limits: AppConfig["limits"] }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<EngineSettings>(initial);
  const save = useMutation({
    mutationFn: (s: EngineSettings) => api.saveEngineSettings(s),
    onSuccess: (s) => {
      queryClient.setQueryData(["settings", "engine"], s);
      toast.success("Engine settings saved", "Running engines were updated.");
    },
    onError: (e) => toast.error("Settings not saved", errorMessage(e)),
  });
  const set = <K extends keyof EngineSettings>(key: K, value: EngineSettings[K]) => setForm({ ...form, [key]: value });
  const num = (v: string) => Math.max(0, Math.round(Number(v) || 0));

  return (
    <Panel>
      <PanelHeader title="Engine resources" icon={<SlidersHorizontal className="size-4" />} subtitle="Defaults are sized for a laptop: a share of the CPU, modest memory" />
      <form
        className="space-y-5 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(form);
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Default engine">
            <select className="field" value={form.default_engine} onChange={(e) => set("default_engine", e.target.value as EngineSettings["default_engine"])}>
              <option value="stockfish">Stockfish</option>
              <option value="custom">ChessLab Engine</option>
            </select>
          </Field>
          <Field label="Candidate lines (MultiPV)" hint={`1–${limits.max_multipv}`}>
            <input type="number" className="field num" min={1} max={limits.max_multipv} value={form.analysis_multipv} onChange={(e) => set("analysis_multipv", num(e.target.value))} />
          </Field>
          <Field label="Stockfish threads" hint={`Max ${limits.max_engine_threads} on this machine. More threads = faster but busier CPU.`}>
            <input type="number" className="field num" min={1} max={limits.max_engine_threads} value={form.stockfish_threads} onChange={(e) => set("stockfish_threads", num(e.target.value))} />
          </Field>
          <Field label="Stockfish hash (MB)" hint={`16–${limits.max_engine_hash_mb} MB`}>
            <input type="number" className="field num" min={16} max={limits.max_engine_hash_mb} step={16} value={form.stockfish_hash_mb} onChange={(e) => set("stockfish_hash_mb", num(e.target.value))} />
          </Field>
          <Field label="Analysis depth limit" hint="Empty = until stopped (with an automatic time cap)">
            <input
              type="number"
              className="field num"
              min={1}
              max={limits.max_search_depth}
              value={form.analysis_depth ?? ""}
              placeholder="∞"
              onChange={(e) => set("analysis_depth", e.target.value ? num(e.target.value) : null)}
            />
          </Field>
          <Field label="Custom engine hash (MB)">
            <input type="number" className="field num" min={8} max={512} value={form.custom_hash_mb} onChange={(e) => set("custom_hash_mb", num(e.target.value))} />
          </Field>
        </div>
        <div className="border-t border-ink-700/70 pt-4">
          <p className="label mb-3">Game review defaults</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Review engine">
              <select className="field" value={form.review_engine} onChange={(e) => set("review_engine", e.target.value as EngineSettings["review_engine"])}>
                <option value="stockfish">Stockfish</option>
                <option value="custom">ChessLab Engine (slow, weak)</option>
              </select>
            </Field>
            <Field label="Depth per position" hint="4–30; 14 is a good balance on a laptop">
              <input type="number" className="field num" min={4} max={30} value={form.review_depth} onChange={(e) => set("review_depth", num(e.target.value))} />
            </Field>
            <Field label="Time cap per position (ms)" hint={`100–${limits.max_review_movetime_ms}`}>
              <input type="number" className="field num" min={100} max={limits.max_review_movetime_ms} step={100} value={form.review_movetime_ms} onChange={(e) => set("review_movetime_ms", num(e.target.value))} />
            </Field>
            <Field label="Review threads">
              <input type="number" className="field num" min={1} max={limits.max_engine_threads} value={form.review_threads} onChange={(e) => set("review_threads", num(e.target.value))} />
            </Field>
            <Field label="Alternative lines per position">
              <input type="number" className="field num" min={1} max={3} value={form.review_multipv} onChange={(e) => set("review_multipv", num(e.target.value))} />
            </Field>
          </div>
        </div>
        <div className="flex gap-2">
          <Button type="submit" variant="primary" icon={<Save className="size-4" />} loading={save.isPending}>
            Save engine settings
          </Button>
          <Button variant="ghost" onClick={() => setForm(initial)}>
            Revert
          </Button>
        </div>
      </form>
    </Panel>
  );
}

function ThresholdsPanel() {
  const current = useQuery({ queryKey: ["settings", "classification"], queryFn: api.thresholds });
  if (!current.data) return <Skeleton className="h-64" />;
  return <ThresholdsForm key={JSON.stringify(current.data)} initial={current.data} />;
}

function ThresholdsForm({ initial }: { initial: ClassificationThresholds }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ClassificationThresholds>(initial);
  const save = useMutation({
    mutationFn: api.saveThresholds,
    onSuccess: (t) => {
      queryClient.setQueryData(["settings", "classification"], t);
      toast.success("Thresholds saved", "New reviews use them. Re-run or reclassify existing reviews to apply them there.");
    },
    onError: (e) => toast.error("Thresholds not saved", errorMessage(e)),
  });
  const keys: (keyof ClassificationThresholds)[] = ["excellent", "good", "inaccuracy", "mistake"];
  return (
    <Panel>
      <PanelHeader title="Review thresholds" subtitle="How much winning chance a move may lose in each category" />
      <div className="space-y-4 p-4">
        <p className="text-xs leading-relaxed text-ink-300">
          A move's loss is the drop in expected score (0–100%) between the engine's best move and the move played, both searched with the same settings. Playing the engine's top move is always “Best”. Losses at or above the mistake bound are blunders. These are ChessLab's own categories, not a copy of any site's labels.
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {keys.map((k) => (
            <Field key={k} label={`${k[0]!.toUpperCase()}${k.slice(1)} below`}>
              <div className="relative">
                <input
                  type="number"
                  className="field num pr-7"
                  min={0.5}
                  max={99}
                  step={0.5}
                  value={Math.round(form[k] * 1000) / 10}
                  onChange={(e) => setForm({ ...form, [k]: Number(e.target.value) / 100 })}
                />
                <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-ink-400">%</span>
              </div>
            </Field>
          ))}
        </div>
        <div className="flex gap-2">
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(form)}>
            Save thresholds
          </Button>
          <Button variant="ghost" onClick={() => setForm({ excellent: 0.02, good: 0.05, inaccuracy: 0.1, mistake: 0.2 })}>
            Restore defaults
          </Button>
        </div>
      </div>
    </Panel>
  );
}

function AppearancePanel() {
  const prefs = usePreferences();
  return (
    <Panel>
      <PanelHeader title="Board & display" icon={<Palette className="size-4" />} subtitle="Saved in this browser" />
      <div className="space-y-4 p-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" role="radiogroup" aria-label="Board theme">
          {(Object.keys(BOARD_THEMES) as BoardThemeId[]).map((id) => {
            const theme = BOARD_THEMES[id];
            return (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={prefs.boardTheme === id}
                onClick={() => prefs.set({ boardTheme: id })}
                className={cn("rounded-lg border p-2 text-left text-xs transition-colors", prefs.boardTheme === id ? "border-brass-500" : "border-ink-600 hover:border-ink-500")}
              >
                <div className="grid aspect-square grid-cols-4 overflow-hidden rounded">
                  {Array.from({ length: 16 }, (_, i) => (
                    <div key={i} style={{ background: (Math.floor(i / 4) + i) % 2 === 0 ? theme.light : theme.dark }} />
                  ))}
                </div>
                <p className="mt-1.5 text-ink-200">{theme.label}</p>
              </button>
            );
          })}
        </div>
        <Toggle checked={prefs.showCoordinates} onChange={(v) => prefs.set({ showCoordinates: v })} label="Show coordinates" />
        <Toggle checked={prefs.animations} onChange={(v) => prefs.set({ animations: v })} label="Animate piece movement" description="Reduced-motion system settings are always respected." />
        <Toggle checked={prefs.showBestArrow} onChange={(v) => prefs.set({ showBestArrow: v })} label="Show the engine's best move as an arrow" />
      </div>
    </Panel>
  );
}

function AccountsPanel() {
  const queryClient = useQueryClient();
  const prefs = useQuery({ queryKey: ["settings", "preferences"], queryFn: api.preferences });
  const save = useMutation({
    mutationFn: api.savePreferences,
    onSuccess: (p) => queryClient.setQueryData(["settings", "preferences"], p),
  });
  return (
    <Panel>
      <PanelHeader title="Linked accounts" icon={<Users className="size-4" />} subtitle="Added automatically after an import; used by “Refresh all”" />
      <div className="p-4">
        {!prefs.data?.accounts.length ? (
          <p className="text-sm text-ink-400">No accounts yet. Import games to link one.</p>
        ) : (
          <ul className="space-y-2">
            {prefs.data.accounts.map((a) => (
              <li key={`${a.provider}-${a.username}`} className="flex items-center justify-between rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-sm">
                <span>
                  {a.username} <span className="text-ink-400">· {a.provider === "chesscom" ? "Chess.com" : "Lichess"}</span>
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => save.mutate({ accounts: prefs.data!.accounts.filter((x) => x !== a) })}
                  aria-label={`Unlink ${a.username}`}
                >
                  Unlink
                </Button>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-xs text-ink-500">Unlinking does not delete imported games.</p>
      </div>
    </Panel>
  );
}

function DataPanel() {
  const queryClient = useQueryClient();
  const info = useQuery({ queryKey: ["data-info"], queryFn: api.dataInfo });
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const backup = useMutation({
    mutationFn: api.backup,
    onSuccess: (b) => {
      toast.success("Backup created", `${b.name} (${formatBytes(b.bytes)}) in your ChessLab data folder.`);
      void queryClient.invalidateQueries({ queryKey: ["data-info"] });
    },
  });
  const wipe = useMutation({
    mutationFn: api.deleteAllGames,
    onSuccess: (r) => {
      toast.success(`Deleted ${plural(r.deleted, "game")}`);
      setConfirmOpen(false);
      setTyped("");
      void queryClient.invalidateQueries();
    },
  });
  return (
    <Panel>
      <PanelHeader title="Your data" icon={<Database className="size-4" />} subtitle="Stored only on this computer" />
      <div className="space-y-4 p-4">
        {info.data ? (
          <dl className="num grid grid-cols-3 gap-3 text-center">
            <div className="rounded-lg bg-ink-900 py-2">
              <dt className="label">Games</dt>
              <dd className="text-lg text-ink-50">{info.data.games.toLocaleString()}</dd>
            </div>
            <div className="rounded-lg bg-ink-900 py-2">
              <dt className="label">Reviews</dt>
              <dd className="text-lg text-ink-50">{info.data.completed_reviews.toLocaleString()}</dd>
            </div>
            <div className="rounded-lg bg-ink-900 py-2">
              <dt className="label">Database</dt>
              <dd className="text-lg text-ink-50">{formatBytes(info.data.database_bytes)}</dd>
            </div>
          </dl>
        ) : (
          <Skeleton className="h-16" />
        )}
        <p className="text-xs text-ink-400">{info.data?.storage}</p>
        <div className="flex flex-wrap gap-2">
          <Button icon={<HardDriveDownload className="size-4" />} loading={backup.isPending} onClick={() => backup.mutate()}>
            Back up database now
          </Button>
          <a href={api.exportUrl({})} download>
            <Button>Export all games (PGN)</Button>
          </a>
          <Button variant="danger" icon={<Trash2 className="size-4" />} onClick={() => setConfirmOpen(true)} disabled={!info.data?.games}>
            Delete all games
          </Button>
        </div>
        {info.data && info.data.backups.length > 0 && (
          <details className="text-xs text-ink-400">
            <summary className="cursor-pointer">{plural(info.data.backups.length, "backup")} available</summary>
            <ul className="num mt-2 space-y-0.5">
              {info.data.backups.map((b) => (
                <li key={b.name}>
                  {b.name} · {formatBytes(b.bytes)}
                </li>
              ))}
            </ul>
            <p className="mt-2">To restore, stop ChessLab and copy a backup over chesslab.db (see docs/operations.md).</p>
          </details>
        )}
      </div>
      <Dialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Delete every stored game?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" disabled={typed !== "DELETE"} loading={wipe.isPending} onClick={() => wipe.mutate()}>
              Delete everything
            </Button>
          </>
        }
      >
        <p>
          This removes all {info.data?.games.toLocaleString()} games and their reviews from the local database. It cannot be undone, so consider a backup first.
        </p>
        <Field label='Type "DELETE" to confirm' htmlFor="confirm-delete">
          <input id="confirm-delete" className="field num mt-1" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
        </Field>
      </Dialog>
    </Panel>
  );
}

function AboutPanel() {
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });
  return (
    <Panel>
      <PanelHeader title="About" icon={<Info className="size-4" />} />
      <div className="space-y-2 p-4 text-xs leading-relaxed text-ink-300">
        <p>ChessLab {config.data ? `v${config.data.version}` : ""}: a local-first chess analysis laboratory. No telemetry; nothing is uploaded. Game imports read public data from Chess.com and Lichess on your request.</p>
        <p>
          Stockfish is free software under the GNU GPL v3 and runs as a separate program. ChessLab's own code is MIT-licensed. Chess pieces are from the react-chessboard package (MIT). See docs/third-party-licenses.md.
        </p>
      </div>
    </Panel>
  );
}
