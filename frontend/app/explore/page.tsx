"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { MessageSquare, AlertTriangle } from "lucide-react";
import { fetchStats } from "@/lib/api";
import { MODE_COLORS, formatCompact, formatNumber } from "@/lib/utils";

interface Stats {
  stations_by_mode: [string, number][];
  routes_by_mode: [string, number][];
  ridership_by_year: [number, string, number][];
  modal_split_latest: [string, number][];
  top_metro_stations: [string, number][];
  top_bus_routes: [string, number][];
  stations_by_zone: [number, number][];
  non_comparable_periods: number;
  indexed_chunks: number;
  data_note: string;
}

export default function ExplorePage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState(false);
  const router = useRouter();

  useEffect(() => {
    fetchStats().then((data) => {
      if (data) setStats(data as unknown as Stats);
      else setError(true);
    });
  }, []);

  function ask(question: string) {
    router.push(`/?q=${encodeURIComponent(question)}`);
  }

  if (error) {
    return (
      <div className="grid flex-1 place-items-center p-8 text-center text-[var(--text-muted)]">
        <div>
          <p className="font-medium">Could not reach the warehouse.</p>
          <p className="mt-1 text-[0.82rem] text-[var(--text-faint)]">
            Start the backend with <code>make dev-api</code>, or build the lakehouse with{" "}
            <code>make etl</code>.
          </p>
        </div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="mx-auto w-full max-w-[1400px] flex-1 space-y-3 p-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="shimmer h-56 rounded-xl" />
        ))}
      </div>
    );
  }

  const trend = buildTrend(stats.ridership_by_year);
  const modes = stats.stations_by_mode.map(([mode, count]) => ({ mode, count }));
  const zones = stats.stations_by_zone.map(([zone, count]) => ({
    zone: `Zone ${zone}`,
    count,
  }));

  return (
    <main className="mx-auto w-full max-w-[1400px] flex-1 space-y-4 p-4">
      <header>
        <h1 className="text-[var(--text-step-2)] font-semibold">Network analytics</h1>
        <p className="mt-1 max-w-3xl text-[0.82rem] leading-relaxed text-[var(--text-muted)]">
          Built from the same gold star schema the agents query. Every chart below excludes
          periods flagged as non-comparable — see the note at the foot of the page.
        </p>
      </header>

      {/* ---- headline tiles ---- */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="Stations held" value={formatNumber(sum(modes.map((m) => m.count)))} hint="across four modes" />
        <Tile label="Routes held" value={formatNumber(sum(stats.routes_by_mode.map(([, n]) => n)))} />
        <Tile label="Indexed chunks" value={formatNumber(stats.indexed_chunks)} hint="documents + row summaries" />
        <Tile
          label="Non-comparable periods"
          value={formatNumber(stats.non_comparable_periods)}
          hint="excluded from every total"
          warn
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel
          title="Ridership by year"
          subtitle="Comparable periods only"
          question="How has metro ridership trended year over year?"
          onAsk={ask}
        >
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={trend} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="year" stroke="var(--text-faint)" fontSize={11} tickLine={false} />
              <YAxis
                stroke="var(--text-faint)"
                fontSize={11}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) => formatCompact(v as number)}
              />
              <Tooltip content={<ChartTooltip />} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {Object.keys(MODE_COLORS).map((mode) =>
                trend.some((row) => row[mode] !== undefined) ? (
                  <Line
                    key={mode}
                    type="monotone"
                    dataKey={mode}
                    stroke={MODE_COLORS[mode]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    connectNulls
                  />
                ) : null,
              )}
            </LineChart>
          </ResponsiveContainer>
        </Panel>

        <Panel
          title="Modal split"
          subtitle="Most recent comparable month"
          question="What is the modal split of Dubai public transport?"
          onAsk={ask}
        >
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={stats.modal_split_latest.map(([type, trips]) => ({ name: type, value: trips }))}
                dataKey="value"
                nameKey="name"
                innerRadius={58}
                outerRadius={98}
                paddingAngle={2}
              >
                {stats.modal_split_latest.map(([type]) => (
                  <Cell key={type} fill={MODE_COLORS[type] ?? "var(--accent)"} stroke="var(--surface)" />
                ))}
              </Pie>
              <Tooltip content={<ChartTooltip />} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
        </Panel>

        <Panel
          title="Busiest metro stations"
          subtitle="Total recorded trips, comparable periods"
          question="Which metro stations are busiest?"
          onAsk={ask}
        >
          <ResponsiveContainer width="100%" height={280}>
            <BarChart
              data={stats.top_metro_stations.map(([name, trips]) => ({
                name: name.replace(/\s*Metro Station\s*/i, "").trim(),
                trips,
              }))}
              layout="vertical"
              margin={{ top: 4, right: 16, left: 8, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
              <XAxis
                type="number"
                stroke="var(--text-faint)"
                fontSize={11}
                tickFormatter={(v) => formatCompact(v as number)}
              />
              <YAxis
                type="category"
                dataKey="name"
                stroke="var(--text-faint)"
                fontSize={10}
                width={112}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--accent-soft)" }} />
              <Bar dataKey="trips" fill={MODE_COLORS.Metro} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>

        <Panel
          title="Stations by fare zone"
          subtitle="Zones determine the nol fare"
          question="How many stations are in each fare zone?"
          onAsk={ask}
        >
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={zones} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="zone" stroke="var(--text-faint)" fontSize={11} tickLine={false} />
              <YAxis stroke="var(--text-faint)" fontSize={11} tickLine={false} axisLine={false} />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--accent-soft)" }} />
              <Bar dataKey="count" fill="var(--accent)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>
      </div>

      <div className="flex items-start gap-2 rounded-xl border border-[var(--loop-border)] bg-[var(--loop-soft)] p-3">
        <AlertTriangle size={15} className="mt-0.5 shrink-0 text-[var(--loop)]" />
        <p className="text-[0.78rem] leading-relaxed text-[var(--text-muted)]">
          <strong className="text-[var(--loop)]">Data note.</strong> {stats.data_note}
        </p>
      </div>
    </main>
  );
}

function buildTrend(rows: [number, string, number][]) {
  const byYear = new Map<number, Record<string, number | string>>();
  for (const [year, mode, trips] of rows) {
    const entry = byYear.get(year) ?? { year };
    entry[mode] = trips;
    byYear.set(year, entry);
  }
  return Array.from(byYear.values()).sort(
    (a, b) => Number(a.year) - Number(b.year),
  ) as Array<Record<string, number> & { year: number }>;
}

const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);

function Tile({
  label,
  value,
  hint,
  warn,
}: {
  label: string;
  value: string;
  hint?: string;
  warn?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="surface p-3"
    >
      <p className="text-[0.66rem] uppercase tracking-[0.12em] text-[var(--text-faint)]">{label}</p>
      <p
        className="mt-1 text-[1.5rem] font-semibold tabular-nums leading-none"
        style={{ color: warn ? "var(--loop)" : "var(--text)" }}
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-[0.68rem] text-[var(--text-faint)]">{hint}</p>}
    </motion.div>
  );
}

function Panel({
  title,
  subtitle,
  question,
  onAsk,
  children,
}: {
  title: string;
  subtitle?: string;
  question: string;
  onAsk: (q: string) => void;
  children: React.ReactNode;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-8%" }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="surface p-3"
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[0.92rem] font-semibold">{title}</h2>
          {subtitle && <p className="text-[0.7rem] text-[var(--text-faint)]">{subtitle}</p>}
        </div>
        <button
          onClick={() => onAsk(question)}
          className="chip chip-idle shrink-0 transition-colors hover:border-[var(--accent-border)] hover:text-[var(--accent)]"
          title={question}
        >
          <MessageSquare size={11} />
          Ask Masar
        </button>
      </div>
      {children}
    </motion.section>
  );
}

interface TooltipProps {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number; color?: string }>;
  label?: string | number;
}

function ChartTooltip({ active, payload, label }: TooltipProps) {
  const data = payload;
  if (!active || !data?.length) return null;
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1.5 shadow-[var(--shadow-md)]">
      {label !== undefined && (
        <p className="mb-1 text-[0.72rem] font-medium text-[var(--text)]">{String(label)}</p>
      )}
      {data.map((entry, index) => (
        <p key={index} className="text-[0.72rem] tabular-nums text-[var(--text-muted)]">
          <span
            className="me-1.5 inline-block h-2 w-2 rounded-full align-middle"
            style={{ background: entry.color ?? "var(--accent)" }}
          />
          {entry.name}: {formatNumber(entry.value ?? 0)}
        </p>
      ))}
    </div>
  );
}
