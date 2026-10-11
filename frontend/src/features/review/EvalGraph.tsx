import { Area, AreaChart, CartesianGrid, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatEval, MOVE_CLASS_META, whiteExpectedScore } from "@/lib/eval";
import type { PositionReview } from "@/types/api";

interface Point {
  ply: number;
  white: number;
  label: string;
  move: string;
}

/** White's expected score over the game (50% = equal). Click to jump to a move. */
export function EvalGraph({ positions, currentPly, onSelect }: { positions: PositionReview[]; currentPly: number; onSelect: (ply: number) => void }) {
  const data: Point[] = positions.map((p) => {
    const turn = p.fen.split(" ")[1] === "b" ? "b" : "w";
    return {
      ply: p.ply,
      white: Math.round(whiteExpectedScore(p.eval, turn) * 1000) / 10,
      label: formatEval(p.eval, turn),
      move: p.move_san ? `${Math.floor((p.ply - 1) / 2) + 1}${p.ply % 2 === 1 ? "." : "..."} ${p.move_san}` : "Start",
    };
  });
  const errors = positions.filter((p) => p.classification === "mistake" || p.classification === "blunder" || p.classification === "inaccuracy");

  return (
    <div className="h-40 w-full cursor-pointer" role="img" aria-label="Evaluation graph: White's winning chances over the game. Use the move list to navigate with a keyboard.">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={data}
          margin={{ top: 6, right: 8, bottom: 0, left: -24 }}
          onClick={(state) => {
            const index = state?.activeTooltipIndex;
            if (typeof index === "number" && data[index]) onSelect(data[index].ply);
            else if (typeof index === "string" && data[Number(index)]) onSelect(data[Number(index)]!.ply);
          }}
        >
          <defs>
            <linearGradient id="evalFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#f1eee8" stopOpacity={0.9} />
              <stop offset="100%" stopColor="#f1eee8" stopOpacity={0.55} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#23282d" vertical={false} />
          <XAxis dataKey="ply" tick={{ fill: "#5c646c", fontSize: 10 }} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={24} />
          <YAxis domain={[0, 100]} ticks={[0, 50, 100]} tick={{ fill: "#5c646c", fontSize: 10 }} tickLine={false} axisLine={false} />
          <ReferenceLine y={50} stroke="#8c672b" strokeDasharray="3 3" />
          <Tooltip
            cursor={{ stroke: "#d6a756", strokeWidth: 1 }}
            contentStyle={{ background: "#181b1f", border: "1px solid #2e343a", borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "#aeb4ba" }}
            formatter={(_value, _name, item) => [(item.payload as Point).label, "Evaluation"]}
            labelFormatter={(_label, payload) => (payload?.[0]?.payload as Point | undefined)?.move ?? ""}
          />
          <Area type="monotone" dataKey="white" stroke="#d9dcdf" strokeWidth={1.5} fill="url(#evalFill)" baseValue={0} isAnimationActive={false} />
          <ReferenceLine x={currentPly} stroke="#d6a756" strokeWidth={1.5} />
          {errors.map((p) => {
            const point = data.find((d) => d.ply === p.ply);
            return point ? <ReferenceDot key={p.ply} x={p.ply} y={point.white} r={3.5} fill={MOVE_CLASS_META[p.classification!].color} stroke="#101215" /> : null;
          })}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
