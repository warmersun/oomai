import React from "react";

const THREE_COL_STYLE = { gridTemplateColumns: "repeat(3, minmax(0, 1fr))" };

const realmColour = (r) => {
  if (r === "bits") return { background: "rgba(255, 99, 132, 0.1)", border: "1px solid rgba(255, 99, 132, 0.2)" };
  if (r === "atoms") return { background: "rgba(54, 162, 235, 0.1)", border: "1px solid rgba(54, 162, 235, 0.2)" };
  return { background: "rgba(153, 102, 255, 0.1)", border: "1px solid rgba(153, 102, 255, 0.2)" };
};

const POWERS = {
  power:      { label: "🦸‍♂️🦸‍♀️ Power",      about: "Energy gives us power. Computing requires energy. Money is stored work." },
  automator:  { label: "🦸‍♂️🦸‍♀️ Automator",  about: "Automating things via algorithms or machines in the physical world." },
  mover:      { label: "🦸‍♂️🦸‍♀️ Mover",      about: "Moving matter in the physical world, or moving bits in the digital world." },
  portal:     { label: "🦸‍♂️🦸‍♀️ Portal",     about: "Bridging real to digital. IoT sensors pull info in, 3D printing pushes it out." },
  link:       { label: "🦸‍♂️🦸‍♀️ Link",       about: "Overlaying the realms. VR/AR mix digital imagination with real sense." },
  lifeforce:  { label: "🦸‍♂️🦸‍♀️ Lifeforce",  about: "Reading and writing the code of life through Synthetic Biology." },
};

function PowerCard({ k }) {
  const { label, about } = POWERS[k] || {};
  const [open, setOpen] = React.useState(false);
  
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "6px", background: "var(--bg-secondary)", overflow: "hidden" }}>
      <div 
        style={{ padding: "8px 12px", fontSize: "0.85rem", fontWeight: "600", cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center", background: "rgba(255,255,255,0.05)" }}
        onClick={() => setOpen(!open)}
      >
        <span>{label}</span>
        <span style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform 0.2s", fontSize: "10px" }}>▼</span>
      </div>
      {open && (
        <div style={{ padding: "8px 12px", fontSize: "0.75rem", color: "var(--text-muted)", borderTop: "1px solid var(--border)", background: "var(--bg-secondary)" }}>
          {about}
        </div>
      )}
    </div>
  );
}

const TECH = {
  computing:      { label: "💻🖥️ Computing",               realm: "bits"  },
  energy:         { label: "⚡🔋🔌🌞 Energy",                  realm: "atoms" },
  crypto:         { label: "💰₿📈 Crypto-currency",         realm: "both",  span: 2 },
  ai:             { label: "🧠🤖 Artificial Intelligence", realm: "bits"  },
  robot:          { label: "🤖🦾 Robotics",                realm: "atoms" },
  networks:       { label: "🌐📡🔗 Networks",                realm: "bits"  },
  transportation: { label: "🚗🚆🚀🚁 Transportation",          realm: "atoms" },
  threeDprinting: { label: "🖨️🧱🔧 3-D Printing",           realm: "atoms" },
  iot:            { label: "📡📱🔌🌐 IoT",                     realm: "both"  },
  arvr:           { label: "🔗 🕶️🎮📱 AR / VR",                realm: "both",  span: 2 },
  synbio:         { label: "🧬🔬🌱➡ Synthetic Biology",       realm: "both",  span: 2 },
};

function TechCard({ k, text }) {
  if (!k) return <div />;

  const { label, realm, span } = TECH[k] || {};
  const styles = realmColour(realm);
  
  return (
    <div 
      style={{ 
        ...styles,
        borderRadius: "6px", 
        overflow: "hidden",
        gridColumn: span === 2 ? "span 2" : "span 1"
      }}
    >
      <div style={{ padding: "6px 12px", fontSize: "0.8rem", fontWeight: "600", borderBottom: styles.border, background: "rgba(0,0,0,0.1)" }}>
        {label}
      </div>
      <div style={{ padding: "8px 12px", fontSize: "0.75rem", color: "var(--text)", whiteSpace: "pre-line", minHeight: "60px" }}>
        {text || "—"}
      </div>
    </div>
  );
}

const ROWS = [
  ["power",      ["computing",      "energy"]            ],
  ["",           ["crypto",         null]                ],
  ["automator",  ["ai",             "robot"]             ],
  ["mover",      ["networks",       "transportation"]    ],
  ["portal",     ["threeDprinting", "iot"]               ],
  ["link",       ["arvr",           null]                ],
  ["lifeforce",  ["synbio",         null]                ],
];

export default function Pathway({ data }) {
  let details = {};
  if (typeof data === 'string') {
    try { details = JSON.parse(data || "{}"); } catch (_) {}
  } else if (typeof data === 'object' && data !== null) {
    details = data;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "12px", margin: "16px 0", padding: "16px", background: "var(--bg-primary)", borderRadius: "8px", border: "1px solid var(--border)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ fontSize: "1.1rem", margin: 0 }}>🛤️ Convergence Canvas</h2>
      </div>

      <div style={{ display: "grid", gap: "12px", gridTemplateColumns: "1fr 1fr 1fr" }}>
        <div />
        <div style={{ padding: "8px", textAlign: "center", fontSize: "0.75rem", fontWeight: "bold", ...realmColour("bits"), borderRadius: "6px" }}>
          Imagined, Information, Digital<br/>World of ℹ Bits
        </div>
        <div style={{ padding: "8px", textAlign: "center", fontSize: "0.75rem", fontWeight: "bold", ...realmColour("atoms"), borderRadius: "6px" }}>
          Real, Physical, Tangible "Stuff"<br/>World of ⚛ Atoms
        </div>
      </div>

      {ROWS.map(([powerKey, [midKey, rightKey]], i) => {
        const wide = TECH[midKey]?.span === 2;
        return (
          <div key={i} style={{ display: "grid", gap: "12px", gridTemplateColumns: "1fr 1fr 1fr" }}>
            {powerKey ? <PowerCard k={powerKey} /> : <div />}
            <TechCard k={midKey} text={details[midKey]} />
            {!wide && (rightKey ? <TechCard k={rightKey} text={details[rightKey]} /> : <div />)}
          </div>
        );
      })}
    </div>
  );
}
