import { useQuery } from "@tanstack/react-query";
import { BookOpenText, Download, Lightbulb, Microscope, Swords, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Button, Callout, EmptyState, PageHeader, Panel, PanelHeader, Skeleton, Stat, WdlBar } from "@/components/ui";
import { api, errorMessage, type GameQuery } from "@/lib/api";
import { MOVE_CLASS_META } from "@/lib/eval";
import { formatDate, formatPercent, plural, SOURCE_LABEL, TIME_CLASS_LABEL } from "@/lib/format";
import type { Insight, StatsSummary, WDL } from "@/types/api";
import { ResultBadge } from "../games/GamesPage";

const TREND_COLORS = ["#d6a756", "#7fb2ff", "#4fbf8a", "#ec8f3e", "#c792ea", "#ef5a52"];
const TOOLTIP_STYLE = { background: "#181b1f", border: "1px solid #2e343a", borderRadius: 8, fontSize: 12 };

export default function DashboardPage() {
  const [owner, setOwner] = useState("");
  const [timeClass, setTimeClass] = useState("");
  const [range, setRangeValue] = useState<"all" | "30" | "90" | "365">("all");
  const [dateFrom, setDateFrom] = useState<string | undefined>(undefined);
  const setRange = (value: typeof range) => {
    setRangeValue(value);
    setDateFrom(value === "all" ? undefined : new Date(Date.now() - Number(value) * 86_400_000).toISOString().slice(0, 10));
  };
  const query: GameQuery = useMemo(() => {
    const q: GameQuery = {};
    if (owner) q.owner = owner;
    if (timeClass) q.time_class = timeClass;
    if (dateFrom) q.date_from = dateFrom;
    return q;
  }, [owner, timeClass, dateFrom]);

  const stats = useQuery({ queryKey: ["stats", query], queryFn: () => api.stats(query) });
  const recent = useQuery({ queryKey: ["games", { ...query, page_size: 6 }], queryFn: () => api.games({ ...query, page_size: 6 }) });
  const filtered = Boolean(owner || timeClass || range !== "all");

  if (stats.isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-72" />
      </div>
    );
  }
  if (stats.isError) {
    return (
      <Callout tone="bad" title="Could not load statistics">
        {errorMessage(stats.error)} Make sure the backend is running (see the README).
      </Callout>
    );
  }
  const s = stats.data;
  if (s.totals.all_games === 0 && !filtered) return <Welcome />;

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description={
          s.totals.first_game
            ? `${plural(s.totals.games, "game")} with your results, ${formatDate(s.totals.first_game)} – ${formatDate(s.totals.last_game)}.`
            : "Statistics from your stored games."
        }
        actions={
          <>
            <select className="field w-auto" value={owner} onChange={(e) => setOwner(e.target.value)} aria-label="Account">
              <option value="">All accounts</option>
              {s.owners.map((o) => (
                <option key={`${o.source}-${o.username}`} value={o.username}>
                  {o.username} · {SOURCE_LABEL[o.source]}
                </option>
              ))}
            </select>
            <select className="field w-auto" value={timeClass} onChange={(e) => setTimeClass(e.target.value)} aria-label="Time control">
              <option value="">All time controls</option>
              {Object.entries(TIME_CLASS_LABEL).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
            <select className="field w-auto" value={range} onChange={(e) => setRange(e.target.value as typeof range)} aria-label="Date range">
              <option value="all">All time</option>
              <option value="30">Last 30 days</option>
              <option value="90">Last 90 days</option>
              <option value="365">Last year</option>
            </select>
          </>
        }
      />

      {s.totals.without_perspective > 0 && (
        <Callout tone="info" className="mb-4" title={`${plural(s.totals.without_perspective, "game")} not counted in results`}>
          These games have no known player for you (e.g. PGN uploads without your name), so wins and losses cannot be attributed.
        </Callout>
      )}

      {s.totals.games === 0 ? (
        <Panel>
          <EmptyState title="No games match these filters">Try a different account, time control or date range.</EmptyState>
        </Panel>
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Games" value={s.totals.games.toLocaleString()} hint={`${s.totals.wins}W · ${s.totals.draws}D · ${s.totals.losses}L`} />
            <Stat label="Score" value={formatPercent(s.totals.score, 1)} hint="Wins + half of draws" accent="var(--color-brass-300)" />
            <Stat
              label="Last 20 games"
              value={formatPercent(s.recent.last_20.score)}
              hint={s.recent.previous_20.games ? `previous 20: ${formatPercent(s.recent.previous_20.score)}` : "not enough earlier games to compare"}
            />
            <Stat label="Average length" value={s.game_length.average_moves ? `${s.game_length.average_moves}` : "–"} hint="moves per game" />
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <Panel className="xl:col-span-2">
              <PanelHeader title="Rating over time" icon={<TrendingUp className="size-4" />} subtitle="Your rating as recorded in each game, by time control" />
              <RatingChart trend={s.rating_trend} />
            </Panel>
            <Panel>
              <PanelHeader title="Results by colour" />
              <div className="space-y-4 p-4">
                <WdlRow label="As White" data={s.by_color.white} />
                <WdlRow label="As Black" data={s.by_color.black} />
              </div>
              <PanelHeader title="Results by time control" />
              <div className="space-y-4 p-4">
                {s.by_time_class.map((row) => (
                  <WdlRow key={row.time_class} label={TIME_CLASS_LABEL[row.time_class] ?? row.time_class} data={row} />
                ))}
              </div>
            </Panel>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <Panel>
              <PanelHeader title="Openings" icon={<BookOpenText className="size-4" />} subtitle="Grouped by opening family; most played first" />
              <OpeningsTable openings={s.openings} />
            </Panel>
            <Panel>
              <PanelHeader title="Potential patterns" icon={<Lightbulb className="size-4" />} subtitle="Inferred from your games: observations, not verdicts" />
              <Insights items={s.insights} totalGames={s.totals.games} reviewed={s.move_quality.reviewed_games} />
            </Panel>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <Panel>
              <PanelHeader title="Move quality" subtitle={s.move_quality.reviewed_games ? `Your moves in ${plural(s.move_quality.reviewed_games, "reviewed game")}` : "Needs reviewed games"} />
              <MoveQuality stats={s} />
            </Panel>
            <Panel>
              <PanelHeader title="How your games end" />
              <Endings endings={s.endings} />
            </Panel>
          </div>

          <Panel>
            <PanelHeader title="Recent games" actions={<Link to="/games"><Button size="sm" variant="ghost">All games</Button></Link>} />
            <ul className="divide-y divide-ink-700/70">
              {recent.data?.items.map((g) => (
                <li key={g.id}>
                  <Link to={`/games/${g.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-ink-800/60">
                    <ResultBadge game={g} />
                    <span className="min-w-0 flex-1 truncate text-sm text-ink-100">
                      vs {g.opponent ?? `${g.white} – ${g.black}`} <span className="num text-xs text-ink-400">{g.opponent_rating ?? ""}</span>
                    </span>
                    <span className="hidden truncate text-xs text-ink-400 sm:block sm:max-w-[240px]">{g.opening}</span>
                    <span className="num text-xs text-ink-400">{formatDate(g.played_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      )}
    </div>
  );
}

function Welcome() {
  return (
    <div>
      <PageHeader title="Welcome to ChessLab" description="A personal chess laboratory that runs on your computer." />
      <Panel>
        <EmptyState
          icon={<Download className="size-6" />}
          title="Start by importing your games"
          actions={
            <>
              <Link to="/import">
                <Button variant="primary" size="lg">
                  Import from Chess.com or Lichess
                </Button>
              </Link>
              <Link to="/import">
                <Button size="lg">Upload a PGN</Button>
              </Link>
            </>
          }
        >
          Enter your username to pull in your public games (no password, no API key). ChessLab stores them locally, reviews them with Stockfish and shows where your games are won and lost.
        </EmptyState>
      </Panel>
      <div className="mt-5 grid gap-4 md:grid-cols-3">
        {[
          { to: "/analysis", icon: Microscope, title: "Analyse a position", text: "Explore lines with live Stockfish evaluation, variations and PGN export." },
          { to: "/play", icon: Swords, title: "Play the engine", text: "Ten Stockfish levels, plus ChessLab's own engine." },
          { to: "/lab", icon: Lightbulb, title: "Engine Lab", text: "Compare Stockfish with the custom engine and inspect its evaluation." },
        ].map(({ to, icon: Icon, title, text }) => (
          <Link key={to} to={to} className="panel group p-5 transition-colors hover:border-ink-500">
            <Icon className="size-5 text-brass-400" />
            <p className="mt-3 font-semibold text-ink-50 group-hover:text-brass-300">{title}</p>
            <p className="mt-1 text-sm text-ink-300">{text}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}

function WdlRow({ label, data }: { label: string; data: WDL }) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between text-sm">
        <span className="text-ink-200">{label}</span>
        <span className="num text-xs text-ink-400">
          {data.games ? `${formatPercent(data.score)} · ${data.wins}/${data.draws}/${data.losses}` : "no games"}
        </span>
      </div>
      <WdlBar wins={data.wins} draws={data.draws} losses={data.losses} />
    </div>
  );
}

function RatingChart({ trend }: { trend: StatsSummary["rating_trend"] }) {
  const classes = Object.keys(trend).filter((k) => trend[k]!.length >= 2);
  const [visible, setVisible] = useState<string | null>(null);
  if (!classes.length) return <p className="px-4 py-12 text-center text-sm text-ink-400">Not enough rated games to draw a trend.</p>;
  const shown = visible && classes.includes(visible) ? [visible] : classes;
  const points = shown.flatMap((tc) => trend[tc]!.map((p) => ({ t: new Date(p.date).getTime(), [tc]: p.rating })));
  points.sort((a, b) => a.t - b.t);
  return (
    <div className="p-2 pr-4">
      <div className="flex flex-wrap gap-1.5 px-3 pb-2">
        {classes.map((tc, i) => (
          <button key={tc} type="button" aria-pressed={visible === tc} onClick={() => setVisible(visible === tc ? null : tc)} className="chip" style={visible === tc ? { borderColor: TREND_COLORS[i % 6] } : undefined}>
            <span className="size-2 rounded-full" style={{ background: TREND_COLORS[i % 6] }} />
            {TIME_CLASS_LABEL[tc] ?? tc}
          </button>
        ))}
      </div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 5, right: 5, bottom: 0, left: -10 }}>
            <CartesianGrid stroke="#23282d" vertical={false} />
            <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} scale="time" tickFormatter={(t: number) => new Date(t).toLocaleDateString(undefined, { month: "short", year: "2-digit" })} tick={{ fill: "#5c646c", fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={40} />
            <YAxis domain={["auto", "auto"]} tick={{ fill: "#5c646c", fontSize: 11 }} tickLine={false} axisLine={false} width={48} />
            <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(t) => new Date(Number(t)).toLocaleDateString()} />
            {shown.map((tc) => (
              <Line key={tc} dataKey={tc} name={TIME_CLASS_LABEL[tc] ?? tc} stroke={TREND_COLORS[classes.indexOf(tc) % 6]} dot={false} strokeWidth={2} connectNulls isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function OpeningsTable({ openings }: { openings: StatsSummary["openings"] }) {
  if (!openings.length) return <p className="px-4 py-10 text-center text-sm text-ink-400">No opening names in these games.</p>;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-[11px] uppercase tracking-wider text-ink-400">
          <th className="px-4 py-2 font-medium">Opening</th>
          <th className="px-2 py-2 text-right font-medium">Games</th>
          <th className="w-1/3 px-4 py-2 font-medium">Results</th>
          <th className="px-4 py-2 text-right font-medium">Score</th>
        </tr>
      </thead>
      <tbody>
        {openings.slice(0, 10).map((o) => (
          <tr key={o.name} className="border-t border-ink-800">
            <td className="max-w-[220px] truncate px-4 py-2 text-ink-100" title={o.name}>
              <Link to={`/games?opening=${encodeURIComponent(o.name.split(" ")[0] ?? o.name)}`} className="hover:text-brass-300">
                {o.name}
              </Link>
            </td>
            <td className="num px-2 py-2 text-right text-ink-300">{o.games}</td>
            <td className="px-4 py-2">
              <WdlBar wins={o.wins} draws={o.draws} losses={o.losses} />
            </td>
            <td className="num px-4 py-2 text-right text-ink-100">{formatPercent(o.score)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Insights({ items, totalGames, reviewed }: { items: Insight[]; totalGames: number; reviewed: number }) {
  return (
    <div className="space-y-3 p-4">
      {items.length === 0 ? (
        <p className="text-sm text-ink-400">
          No clear patterns yet. Patterns appear only when there is enough evidence (for example at least 5 games in an opening or 10 per colour)
          {reviewed === 0 ? ". Reviewing games with the engine unlocks move-quality patterns." : "."}
        </p>
      ) : (
        items.map((item) => (
          <div key={`${item.kind}-${item.title}`} className="rounded-xl border border-ink-700 bg-ink-900 p-3">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium text-ink-50">{item.title}</p>
              <Badge tone={item.confidence === "high" ? "good" : item.confidence === "medium" ? "brass" : "neutral"}>{item.confidence} confidence</Badge>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-ink-300">{item.detail}</p>
            <p className="mt-1 text-[11px] text-ink-500">Based on {item.sample_size} {item.kind === "tactics" || item.kind === "phase" || item.kind === "time_pressure" ? "moves/positions" : "games"}.</p>
          </div>
        ))
      )}
      <p className="text-[11px] text-ink-500">
        Calculated from {plural(totalGames, "game")}. Small samples can mislead; treat these as prompts for study, not as a measure of your strength.
      </p>
    </div>
  );
}

function MoveQuality({ stats }: { stats: StatsSummary }) {
  const mq = stats.move_quality;
  if (!mq.reviewed_games)
    return (
      <EmptyState title="No reviewed games yet" actions={<Link to="/games"><Button size="sm">Choose games to review</Button></Link>}>
        Run an engine review on some games to see how often your moves are best, inaccurate or blunders.
      </EmptyState>
    );
  const data = (Object.keys(mq.counts) as (keyof typeof mq.counts)[]).map((k) => ({ name: MOVE_CLASS_META[k].label, value: mq.counts[k], color: MOVE_CLASS_META[k].color }));
  return (
    <div className="space-y-2 p-4">
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 5, right: 5, bottom: 0, left: -20 }}>
            <CartesianGrid stroke="#23282d" vertical={false} />
            <XAxis dataKey="name" tick={{ fill: "#868e96", fontSize: 11 }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fill: "#5c646c", fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals={false} />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
            <Bar dataKey="value" name="Moves" radius={[4, 4, 0, 0]} isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.name} fill={d.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center">
        {(["opening", "middlegame", "endgame"] as const).map((phase) => (
          <div key={phase} className="rounded-lg bg-ink-900 px-2 py-2">
            <p className="label">{phase}</p>
            <p className="num mt-1 text-sm text-ink-50">{formatPercent(mq.by_phase[phase].rate, 1)}</p>
            <p className="text-[10px] text-ink-500">mistakes+blunders of {mq.by_phase[phase].moves} moves</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Endings({ endings }: { endings: StatsSummary["endings"] }) {
  const order = ["checkmate", "resignation", "timeout", "draw", "abandoned", "other", "unknown"];
  const rows = order.filter((k) => endings[k]).map((k) => ({ kind: k, ...endings[k]! }));
  if (!rows.length) return <p className="px-4 py-10 text-center text-sm text-ink-400">No termination data.</p>;
  return (
    <div className="h-64 p-2 pr-4">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 5, right: 5, bottom: 0, left: 10 }}>
          <CartesianGrid stroke="#23282d" horizontal={false} />
          <XAxis type="number" tick={{ fill: "#5c646c", fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals={false} />
          <YAxis type="category" dataKey="kind" tick={{ fill: "#aeb4ba", fontSize: 11 }} tickLine={false} axisLine={false} width={84} />
          <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="win" name="Won" stackId="a" fill="#4fbf8a" isAnimationActive={false} />
          <Bar dataKey="draw" name="Drawn" stackId="a" fill="#6b747d" isAnimationActive={false} />
          <Bar dataKey="loss" name="Lost" stackId="a" fill="#ef5a52" radius={[0, 4, 4, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
      <p className="px-3 text-[11px] text-ink-500">“other” includes Lichess's “Normal” result, which does not distinguish mate from resignation.</p>
    </div>
  );
}
