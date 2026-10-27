import { useEffect, useState } from "react";
import { motion } from "framer-motion";

type ModuleRow = {
  module: string;
  static_clean: boolean;
  agreement_pct: number;
  seeds: number;
  mismatches: number;
  any_density: number;
  iterations: number;
  tokens: number;
};

type Trap = { id: string; description: string; caught: boolean; mismatches: number };
type Report = { version: number; generated_at: string; modules: ModuleRow[]; traps: Trap[] };

export default function App() {
  const [report, setReport] = useState<Report | null>(null);
  useEffect(() => {
    fetch("run-report.json")
      .then((r) => r.json())
      .then(setReport);
  }, []);
  if (!report) return <div className="p-8">Loading run report…</div>;
  return (
    <div className="mx-auto max-w-4xl p-8">
      <h1 className="text-2xl font-bold">Migration replay</h1>
      <p className="text-sm text-gray-500">{report.generated_at}</p>
      <h2 className="mt-6 text-lg font-semibold">Modules</h2>
      <table className="mt-2 w-full text-sm">
        <thead>
          <tr className="text-left">
            <th>module</th>
            <th>static</th>
            <th>agreement</th>
            <th>seeds</th>
            <th>iters</th>
            <th>tokens</th>
          </tr>
        </thead>
        <tbody>
          {report.modules.map((m) => (
            <motion.tr key={m.module} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <td>{m.module}</td>
              <td>{m.static_clean ? "clean" : "dirty"}</td>
              <td>{m.agreement_pct}%</td>
              <td>{m.seeds}</td>
              <td>{m.iterations}</td>
              <td>{m.tokens}</td>
            </motion.tr>
          ))}
        </tbody>
      </table>
      <h2 className="mt-6 text-lg font-semibold">Traps</h2>
      <ul>
        {report.traps.map((t) => (
          <motion.li
            key={t.id}
            initial={{ x: -8, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            className="mt-1"
          >
            {t.caught ? "✅" : "❌"} <b>{t.id}</b> — {t.description}
          </motion.li>
        ))}
      </ul>
    </div>
  );
}
