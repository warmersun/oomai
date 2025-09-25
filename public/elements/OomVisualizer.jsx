// public/elements/OomVisualiser.jsx
import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";

export default function OomVisualiser() {
  // monthsPerDoubling is injected via props
  const monthsPerDoubling = props.monthsPerDoubling || 12;
  const TARGETS = [1, 10, 100, 1000];

  const [doublings, setDoublings] = useState(0);
  const [target, setTarget] = useState(100);
  const [projection, setProjection] = useState("");

  // Calculate summary values
  const need = Math.ceil(Math.log2(target));
  const totalMonths = need * monthsPerDoubling;
  const years = Math.floor(totalMonths / 12);
  const months = totalMonths % 12;

  // Update projection date when doublings change
  useEffect(() => {
    const future = new Date();
    future.setMonth(future.getMonth() + doublings * monthsPerDoubling);
    setProjection(future.toLocaleDateString(undefined, { month: "short", year: "numeric" }));
  }, [doublings, monthsPerDoubling]);

  // Determine number of filled cells
  const filled = Math.min(1024, 2 ** doublings);

  return (
    <div className="flex flex-col items-center gap-4 my-4">
      {/* Slider Controls */}
      <div className="flex items-center gap-2">
        <Button onClick={() => setDoublings(d => Math.max(0, d - 1))} variant="outline">‹</Button>
        <input
          type="range"
          min={0}
          max={10}
          value={doublings}
          onChange={e => setDoublings(+e.target.value)}
          className="w-64"
        />
        <Button onClick={() => setDoublings(d => Math.min(10, d + 1))} variant="outline">›</Button>
      </div>

      {/* Slider Info */}
      <div className="text-sm text-secondary">
        {doublings} / 10 doublings → <strong>{doublings * monthsPerDoubling}</strong> mo ⇒ <strong>{projection}</strong>
      </div>

      {/* Summary */}
      <div className="text-center">
        Goal: <strong>{target}×</strong> ⇒ <strong>{need} doublings</strong><br />
        ETA @ <strong>{monthsPerDoubling} mo/doubling</strong> ≈ <strong>{years} y {months} m</strong>
      </div>

      {/* Exponential Grid */}
      <div
        className="grid bg-white p-4 rounded-2xl shadow"
        style={{ gridTemplateColumns: "repeat(32, 1fr)", gap: "2px", width: "min(80vw, 640px)" }}
      >
        {Array.from({ length: 1024 }).map((_, i) => (
          <div
            key={i}
            style={{
              backgroundColor: i < filled ? "#b91c1c" : i < target ? "#eab308" : "#94a3b8",
              width: "100%",
              paddingTop: "100%",
              borderRadius: ".125rem"
            }}
          />
        ))}
      </div>

      {/* Target Buttons */}
      <div className="flex flex-wrap gap-2">
        {TARGETS.map(f => (
          <Button
            key={f}
            size="sm"
            variant={f === target ? "destructive" : "outline"}
            onClick={() => setTarget(f)}
          >
            {f}×
          </Button>
        ))}
      </div>
    </div>
  );
}