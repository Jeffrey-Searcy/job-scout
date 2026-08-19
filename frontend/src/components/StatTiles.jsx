// Row of headline numbers (KPIs) across the top of the dashboard.
import React from "react";

// Render the headline stat tiles from the /stats payload. The "active" tile is
// highlighted because an in-progress interview is the thing that matters most.
// Offer and rejected counts come from stats.by_status (a {status: count} map),
// defaulting to 0 when no application has reached that status yet.
export default function StatTiles({ stats }) {
  if (!stats) return null;
  const byStatus = stats.by_status || {};
  const tiles = [
    { n: stats.total, l: "Applications out" },
    { n: stats.active, l: "In an interview process", hl: true },
    { n: byStatus.offer || 0, l: "Offers" },
    { n: byStatus.rejected || 0, l: "Rejected" },
    { n: stats.local, l: "Local" },
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
