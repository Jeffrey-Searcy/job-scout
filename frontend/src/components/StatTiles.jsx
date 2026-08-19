// Row of headline numbers (KPIs) across the top of the dashboard.
import React from "react";

// Render four stat tiles from the /stats payload. The "active" tile is
// highlighted because an in-progress interview is the thing that matters most.
export default function StatTiles({ stats }) {
  if (!stats) return null;
  const tiles = [
    { n: stats.total, l: "Applications out" },
    { n: stats.active, l: "In an interview process", hl: true },
    { n: stats.local, l: "Tampa Bay / local" },
    { n: stats.strong, l: "Strong-fit targets" },
  ];
  return (
    <div className="tiles">
      {tiles.map((t, i) => (
        <div className={`tile ${t.hl ? "hl" : ""}`} key={i}>
          <div className="n">{t.n}</div>
          <div className="l">{t.l}</div>
        </div>
      ))}
    </div>
  );
}
