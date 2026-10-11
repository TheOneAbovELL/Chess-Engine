import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, CloudDownload, FileUp, Lock, RefreshCw, RotateCcw, Square, UserCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Badge, Button, Callout, Field, PageHeader, Panel, PanelHeader, ProgressBar, Segmented } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDate, plural, relativeTime, TIME_CLASS_LABEL } from "@/lib/format";
import { toast } from "@/stores/toast";
import type { ImportJob, ImportParams, JobStatus, ProviderId, ProviderUser, UploadSummary } from "@/types/api";

const PRESETS = [25, 50, 100] as const;
const TIME_CLASSES = ["bullet", "blitz", "rapid", "classical", "correspondence"] as const;
const ACTIVE: JobStatus[] = ["queued", "running"];

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const map: Record<JobStatus, { tone: "neutral" | "good" | "warn" | "bad" | "info"; label: string }> = {
    queued: { tone: "info", label: "Queued" },
    running: { tone: "info", label: "Running" },
    completed: { tone: "good", label: "Completed" },
    partial: { tone: "warn", label: "Partially completed" },
    failed: { tone: "bad", label: "Failed" },
    cancelled: { tone: "neutral", label: "Cancelled" },
  };
  return <Badge tone={map[status].tone}>{map[status].label}</Badge>;
}

export default function ImportPage() {
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const prefs = useQuery({ queryKey: ["settings", "preferences"], queryFn: api.preferences });
  const queryClient = useQueryClient();

  const [provider, setProvider] = useState<ProviderId>("chesscom");
  const [username, setUsername] = useState("");
  const [amount, setAmount] = useState<string>("50");
  const [custom, setCustom] = useState(200);
  const [mode, setMode] = useState<"recent" | "refresh">("recent");
  const [advanced, setAdvanced] = useState(false);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [timeClasses, setTimeClasses] = useState<string[]>([]);
  const [color, setColor] = useState<"" | "white" | "black">("");
  const [rated, setRated] = useState<"" | "true" | "false">("");
  const [lookedUp, setLookedUp] = useState<{ key: string; user: ProviderUser } | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const maxGames = config.data?.limits.max_import_games ?? 5000;
  const providerInfo = providers.data?.find((p) => p.id === provider);
  const validUsername = /^[A-Za-z0-9][A-Za-z0-9_-]{1,29}$/.test(username.trim());

  const accountKey = `${provider}:${username.trim().toLowerCase()}`;
  const account = lookedUp?.key === accountKey ? lookedUp.user : null;
  const lookup = useMutation({
    mutationFn: () => api.lookupUser(provider, username.trim()),
    onSuccess: (user) => setLookedUp({ key: accountKey, user }),
    onError: () => setLookedUp(null),
  });

  const jobs = useQuery({
    queryKey: ["imports"],
    queryFn: api.imports,
    refetchInterval: (q) => (q.state.data?.some((j) => ACTIVE.includes(j.status)) ? 2000 : false),
  });
  const activeJob = useQuery({
    queryKey: ["import", activeJobId],
    queryFn: () => api.importJob(activeJobId!),
    enabled: Boolean(activeJobId),
    refetchInterval: (q) => (q.state.data && !ACTIVE.includes(q.state.data.status) ? false : 1000),
  });

  // When a job finishes, refresh everything that depends on games.
  const finishedStatus = activeJob.data && !ACTIVE.includes(activeJob.data.status) ? activeJob.data.status : null;
  useEffect(() => {
    if (!finishedStatus) return;
    void queryClient.invalidateQueries({ queryKey: ["games"] });
    void queryClient.invalidateQueries({ queryKey: ["stats"] });
    void queryClient.invalidateQueries({ queryKey: ["owners"] });
    void queryClient.invalidateQueries({ queryKey: ["imports"] });
  }, [finishedStatus, queryClient]);

  const start = useMutation({
    mutationFn: (params: ImportParams) => api.startImport(params),
    onSuccess: (job) => {
      setActiveJobId(job.id);
      void queryClient.invalidateQueries({ queryKey: ["imports"] });
    },
    onError: (e) => toast.error("Could not start the import", errorMessage(e)),
  });
  const refreshAll = useMutation({
    mutationFn: api.refreshAll,
    onSuccess: (created) => {
      toast.success(created.length ? `Checking ${plural(created.length, "account")} for new games` : "No linked accounts to refresh");
      if (created[0]) setActiveJobId(created[0].id);
      void queryClient.invalidateQueries({ queryKey: ["imports"] });
    },
  });

  const submit = () => {
    const max = amount === "all" ? maxGames : amount === "custom" ? Math.min(Math.max(1, custom), maxGames) : Number(amount);
    start.mutate({
      provider,
      username: username.trim(),
      mode: amount === "all" && mode === "recent" ? "all" : mode,
      max_games: mode === "refresh" ? maxGames : max,
      since: since || null,
      until: until || null,
      time_classes: timeClasses as ImportParams["time_classes"],
      color: color || null,
      rated: rated === "" ? null : rated === "true",
    });
  };

  return (
    <div>
      <PageHeader
        title="Import Games"
        description="Bring in your public game history from Chess.com or Lichess using their free, official APIs, or upload PGN files."
        actions={
          prefs.data?.accounts.length ? (
            <Button icon={<RefreshCw className="size-4" />} loading={refreshAll.isPending} onClick={() => refreshAll.mutate()}>
              Refresh all linked accounts
            </Button>
          ) : undefined
        }
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-5">
          <Panel>
            <PanelHeader title="From an online account" icon={<CloudDownload className="size-4" />} />
            <div className="space-y-5 p-4">
              <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Platform">
                {(["chesscom", "lichess"] as const).map((id) => (
                  <button
                    key={id}
                    type="button"
                    role="radio"
                    aria-checked={provider === id}
                    onClick={() => setProvider(id)}
                    className={cn(
                      "rounded-xl border p-4 text-left transition-colors",
                      provider === id ? "border-brass-500 bg-brass-500/5" : "border-ink-600 bg-ink-900 hover:border-ink-500",
                    )}
                  >
                    <p className="font-semibold text-ink-50">{id === "chesscom" ? "Chess.com" : "Lichess"}</p>
                    <p className="mt-1 text-xs text-ink-300">{id === "chesscom" ? "Published-Data API · monthly archives" : "Public games export · streamed PGN"}</p>
                  </button>
                ))}
              </div>

              <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
                <Field label={`${provider === "chesscom" ? "Chess.com" : "Lichess"} username`} htmlFor="username" error={username && !validUsername ? "Usernames are 2–30 letters, digits, '_' or '-'." : null}>
                  <input
                    id="username"
                    className="field"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="e.g. magnuscarlsen"
                    autoComplete="off"
                    spellCheck={false}
                    onKeyDown={(e) => e.key === "Enter" && validUsername && lookup.mutate()}
                  />
                </Field>
                <Button icon={<UserCheck className="size-4" />} disabled={!validUsername} loading={lookup.isPending} onClick={() => lookup.mutate()}>
                  Check account
                </Button>
              </div>
              {lookup.isError && <Callout tone="bad">{errorMessage(lookup.error)}</Callout>}
              {account && <AccountCard user={account} />}

              <Field label="What to import">
                <Segmented
                  label="Mode"
                  value={mode}
                  onChange={setMode}
                  options={[
                    { value: "recent", label: "Recent games" },
                    { value: "refresh", label: "Only new games since last import" },
                  ]}
                />
              </Field>

              {mode === "recent" && (
                <Field label="How many" hint={amount === "all" ? `Imports up to ${maxGames.toLocaleString()} games (newest first). Large histories take a while.` : undefined}>
                  <div className="flex flex-wrap items-center gap-2">
                    <Segmented
                      label="Number of games"
                      value={amount}
                      onChange={setAmount}
                      options={[...PRESETS.map((n) => ({ value: String(n), label: `Latest ${n}` })), { value: "custom", label: "Custom" }, { value: "all", label: "All history" }]}
                    />
                    {amount === "custom" && (
                      <input type="number" min={1} max={maxGames} className="field num w-28" value={custom} onChange={(e) => setCustom(Number(e.target.value))} aria-label="Custom number of games" />
                    )}
                  </div>
                </Field>
              )}

              <button type="button" className="flex items-center gap-1.5 text-sm text-ink-300 hover:text-ink-100" onClick={() => setAdvanced((v) => !v)} aria-expanded={advanced}>
                <ChevronDown className={cn("size-4 transition-transform", advanced && "rotate-180")} /> Filters (optional)
              </button>
              {advanced && (
                <div className="grid gap-4 rounded-xl border border-ink-700 bg-ink-900/50 p-4 sm:grid-cols-2">
                  <Field label="Played on or after">
                    <input type="date" className="field" value={since} onChange={(e) => setSince(e.target.value)} />
                  </Field>
                  <Field label="Played on or before">
                    <input type="date" className="field" value={until} onChange={(e) => setUntil(e.target.value)} />
                  </Field>
                  <div className="sm:col-span-2">
                    <p className="mb-1.5 text-xs font-medium text-ink-200">Time controls (none selected = all)</p>
                    <div className="flex flex-wrap gap-1.5">
                      {TIME_CLASSES.map((tc) => {
                        const on = timeClasses.includes(tc);
                        return (
                          <button
                            key={tc}
                            type="button"
                            aria-pressed={on}
                            onClick={() => setTimeClasses((list) => (on ? list.filter((x) => x !== tc) : [...list, tc]))}
                            className={cn("chip", on && "border-brass-500 bg-brass-500/10 text-brass-300")}
                          >
                            {TIME_CLASS_LABEL[tc]}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <Field label="Your colour">
                    <select className="field" value={color} onChange={(e) => setColor(e.target.value as typeof color)}>
                      <option value="">Both</option>
                      <option value="white">White only</option>
                      <option value="black">Black only</option>
                    </select>
                  </Field>
                  <Field label="Rated">
                    <select className="field" value={rated} onChange={(e) => setRated(e.target.value as typeof rated)}>
                      <option value="">Rated and casual</option>
                      <option value="true">Rated only</option>
                      <option value="false">Casual only</option>
                    </select>
                  </Field>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-3">
                <Button variant="primary" size="lg" icon={<CloudDownload className="size-4" />} disabled={!validUsername} loading={start.isPending} onClick={submit}>
                  Start import
                </Button>
                <p className="flex items-center gap-1.5 text-xs text-ink-400">
                  <Lock className="size-3.5" /> No password needed. Only public games are read, and they are stored only on this computer.
                </p>
              </div>
              {providerInfo && (
                <ul className="space-y-1 border-t border-ink-700/70 pt-3 text-xs text-ink-400">
                  {providerInfo.notes.map((n) => (
                    <li key={n}>• {n}</li>
                  ))}
                  <li>
                    • Private, deleted or restricted games cannot be imported.{" "}
                    <a className="text-brass-400 hover:underline" href={providerInfo.docs} target="_blank" rel="noreferrer noopener">
                      API documentation
                    </a>
                  </li>
                </ul>
              )}
            </div>
          </Panel>

          {activeJob.data && <JobCard job={activeJob.data} onRetry={(id) => api.retryImport(id).then((j) => setActiveJobId(j.id))} />}
          {activeJob.isError && <Callout tone="bad">{errorMessage(activeJob.error)}</Callout>}
        </div>

        <div className="space-y-5">
          <PgnUpload />
          <Panel>
            <PanelHeader title="Recent imports" />
            {jobs.data?.length ? (
              <ul className="divide-y divide-ink-700/70">
                {jobs.data.map((job) => (
                  <li key={job.id}>
                    <button type="button" className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left hover:bg-ink-800/60" onClick={() => setActiveJobId(job.id)}>
                      <div className="min-w-0">
                        <p className="truncate text-sm text-ink-100">
                          {job.username} <span className="text-ink-400">· {job.provider === "chesscom" ? "Chess.com" : "Lichess"}</span>
                        </p>
                        <p className="text-xs text-ink-400">
                          {plural(job.imported, "new game")} · {relativeTime(job.created_at)}
                        </p>
                      </div>
                      <JobStatusBadge status={job.status} />
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-4 py-6 text-center text-sm text-ink-400">No imports yet.</p>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function AccountCard({ user }: { user: ProviderUser }) {
  const counts = Object.entries(user.game_counts).filter(([k]) => k !== "all");
  return (
    <div className={cn("rounded-xl border p-3.5 text-sm", user.closed ? "border-q-inaccuracy/40 bg-q-inaccuracy/5" : "border-q-best/30 bg-q-best/5")}>
      <div className="flex flex-wrap items-center gap-2">
        <UserCheck className="size-4 text-q-best" />
        <span className="font-semibold text-ink-50">{user.username}</span>
        {user.status && <Badge>{user.status}</Badge>}
        {user.url && (
          <a href={user.url} target="_blank" rel="noreferrer noopener" className="text-xs text-brass-400 hover:underline">
            View profile
          </a>
        )}
      </div>
      <p className="mt-1 text-xs text-ink-300">
        {user.joined && `Joined ${formatDate(user.joined)}`}
        {user.last_online && ` · last online ${relativeTime(user.last_online)}`}
        {user.game_counts.all !== undefined && ` · ${user.game_counts.all.toLocaleString()} games on record`}
      </p>
      {counts.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {counts.slice(0, 6).map(([k, v]) => (
            <span key={k} className="chip">
              {k}: {v.toLocaleString()}
            </span>
          ))}
        </div>
      )}
      {user.notes.map((n) => (
        <p key={n} className="mt-2 text-xs text-q-inaccuracy">
          {n}
        </p>
      ))}
    </div>
  );
}

function JobCard({ job, onRetry }: { job: ImportJob; onRetry: (id: string) => Promise<unknown> }) {
  const queryClient = useQueryClient();
  const [showErrors, setShowErrors] = useState(false);
  const running = ACTIVE.includes(job.status);
  const cancel = useMutation({ mutationFn: () => api.cancelImport(job.id), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["import", job.id] }) });
  const retry = useMutation({ mutationFn: () => onRetry(job.id) });
  const target = job.params.mode === "refresh" ? null : job.params.max_games;
  const tone = job.status === "completed" ? "good" : job.status === "partial" ? "warn" : job.status === "failed" ? "bad" : "info";

  return (
    <Panel aria-live="polite">
      <PanelHeader
        title={`Import · ${job.username}`}
        subtitle={job.provider === "chesscom" ? "Chess.com" : "Lichess"}
        actions={
          <>
            <JobStatusBadge status={job.status} />
            {running && (
              <Button size="sm" variant="ghost" icon={<Square className="size-3" />} loading={cancel.isPending} onClick={() => cancel.mutate()}>
                Cancel
              </Button>
            )}
          </>
        }
      />
      <div className="space-y-4 p-4">
        {running && (
          <div className="space-y-1.5">
            <ProgressBar value={target ? job.discovered : job.discovered ? 1 : 0} max={target ?? 1} label="Import progress" />
            <p className="text-xs text-ink-300">{job.phase ?? "Working…"}</p>
          </div>
        )}
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {[
            ["Found", job.discovered],
            ["Imported", job.imported],
            ["Already had", job.duplicates],
            ["Skipped", job.skipped],
            ["Failed", job.failed],
          ].map(([label, value]) => (
            <div key={label as string} className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2">
              <dt className="label">{label}</dt>
              <dd className={cn("num mt-0.5 text-lg font-semibold", label === "Failed" && Number(value) > 0 ? "text-q-blunder" : "text-ink-50")}>{Number(value).toLocaleString()}</dd>
            </div>
          ))}
        </dl>
        {job.message && !running && (
          <Callout tone={tone as "good" | "warn" | "bad" | "info"} title={job.status === "completed" ? "Import complete" : job.status === "partial" ? "Import partially completed" : job.status === "failed" ? "Import failed" : "Import cancelled"}>
            {job.message}
          </Callout>
        )}
        {job.errors.length > 0 && (
          <div>
            <button type="button" className="text-xs text-ink-300 hover:text-ink-100" onClick={() => setShowErrors((v) => !v)} aria-expanded={showErrors}>
              {showErrors ? "Hide" : "Show"} details ({job.errors.length})
            </button>
            {showErrors && (
              <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto rounded-lg border border-ink-700 bg-ink-900 p-2 text-xs">
                {job.errors.map((e, i) => (
                  <li key={i} className="text-ink-300">
                    <span className="num text-ink-400">{e.ref}</span>: {e.error}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {!running && (
          <div className="flex flex-wrap gap-2">
            {job.imported + job.duplicates > 0 && (
              <Link to={`/games?owner=${encodeURIComponent(job.username)}&source=${job.provider}`}>
                <Button variant="primary">View games</Button>
              </Link>
            )}
            {(job.status === "failed" || job.status === "partial" || job.status === "cancelled") && (
              <Button icon={<RotateCcw className="size-4" />} loading={retry.isPending} onClick={() => retry.mutate()}>
                Retry
              </Button>
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}

function PgnUpload() {
  const queryClient = useQueryClient();
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });
  const [text, setText] = useState("");
  const [owner, setOwner] = useState("");
  const [fileNames, setFileNames] = useState<string[]>([]);
  const [summary, setSummary] = useState<UploadSummary | null>(null);
  const maxBytes = config.data?.limits.max_pgn_bytes ?? 5 * 1024 * 1024;
  const tooLarge = new Blob([text]).size > maxBytes;

  const upload = useMutation({
    mutationFn: () => api.importPgn(text, owner.trim() || undefined),
    onSuccess: (s) => {
      setSummary(s);
      toast.success(`Imported ${plural(s.imported, "game")}`);
      void queryClient.invalidateQueries({ queryKey: ["games"] });
      void queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: () => setSummary(null),
  });

  return (
    <Panel>
      <PanelHeader title="Upload PGN" icon={<FileUp className="size-4" />} />
      <div className="space-y-3 p-4">
        <input
          type="file"
          accept=".pgn,text/plain"
          multiple
          aria-label="Choose PGN files"
          className="block w-full text-xs text-ink-300 file:mr-3 file:rounded-md file:border-0 file:bg-ink-700 file:px-3 file:py-1.5 file:text-ink-100 hover:file:bg-ink-600"
          onChange={async (e) => {
            const files = [...(e.target.files ?? [])];
            setFileNames(files.map((f) => f.name));
            setText((await Promise.all(files.map((f) => f.text()))).join("\n\n"));
            setSummary(null);
          }}
        />
        <textarea className="field num h-28 resize-y text-xs" placeholder="…or paste PGN here" value={text} onChange={(e) => setText(e.target.value)} aria-label="PGN text" />
        {fileNames.length > 0 && <p className="text-xs text-ink-400">{fileNames.join(", ")}</p>}
        <Field label="Your name in these games (optional)" hint="Lets ChessLab compute your results and statistics.">
          <input className="field" value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="e.g. MyHandle" />
        </Field>
        {tooLarge && <Callout tone="warn">This text is larger than the {Math.round(maxBytes / 1024 / 1024)} MB upload limit. Split the file and upload it in parts.</Callout>}
        <Button variant="primary" className="w-full" disabled={!text.trim() || tooLarge} loading={upload.isPending} onClick={() => upload.mutate()}>
          Import PGN
        </Button>
        {upload.isError && <Callout tone="bad" title="Import failed">{errorMessage(upload.error)}</Callout>}
        {summary && (
          <Callout tone={summary.failed ? "warn" : "good"} title={`${summary.imported} imported · ${summary.duplicates} already in library · ${summary.failed} invalid${summary.skipped ? ` · ${summary.skipped} skipped` : ""}`}>
            {summary.errors.slice(0, 5).map((e) => (
              <p key={e.index} className="text-xs">
                Game {e.index + 1}
                {e.game ? ` (${e.game})` : ""}: {e.error}
              </p>
            ))}
          </Callout>
        )}
      </div>
    </Panel>
  );
}
