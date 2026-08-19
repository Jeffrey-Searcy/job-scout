// Cumulative funnel: how many applications reached each stage or beyond.
import React from "react";

// Ordered stages + a single-hue sequential ramp (darker = deeper in the funnel).
const STAGES = [
  { key: "applied", name: "Applied" },
  { key: "phone_screen", name: "Phone screen" },
  { key: "interview", name: "Interview" },
  { key: "offer", name: "Offer" },
];
const SHADES = ["#4f46e5", "#5b53e8", "#6f68ec", "#8a84f0"];

// Draw one horizontal bar per stage, widths proportional to the max count.
export default function PipelineFunnel({ funnel }) {
  if (!funnel) return null;
  const max = Math.max(...STAGES.map((s) => funnel[s.key] || 0), 1);
  return (
    <div className="panel">
      <h2>Pipeline</h2>
      <div className="funnel">
        {STAGES.map((s, i) => {
          const count = funnel[s.key] || 0;
          const width = Math.max((count / max) * 100, count ? 3 : 0);
          return (
            <div className="stage" key={s.key} title={`${s.name}: ${count}`}>
              <span className="name">{s.name}</span>
              <span className="track">
                <span className="fill" style={{ width: `${width}%`, background: SHADES[i] }} />
              </span>
              <span className="c">{count}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
