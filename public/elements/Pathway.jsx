/* global props, deleteElement */
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ChevronDown, Trash2 } from "lucide-react";
import { useState } from "react";

/* ———————————————————————————————  helpers —————————————————————————————— */

const THREE_COL_STYLE = { gridTemplateColumns: "repeat(3, minmax(0, 1fr))" };
const DARK_TEXT = { color: "#111827" };             // near-black
const realmColour = (r) =>
  r === "bits"
    ? "bg-red-50"
    : r === "atoms"
    ? "bg-blue-50"
    : "bg-purple-50";


/* Realm banner cards (row 0) */
function RealmBanner({ label, realm }) {
  return (
    <Card className={realmColour(realm) + " border-muted/20 col-span-1"}>
      <CardContent
        className="py-3 text-xs font-medium whitespace-pre-line text-center"
        style={DARK_TEXT}
      >
        {label}
      </CardContent>
    </Card>
  );
}

/* Super-power cards (left column) */
const POWERS = {
  power:      { label: "🦸‍♂️🦸‍♀️ Power",      about: " The \"Power\" superpower 😜. Energy gives us power. And yes, everything in the world of information needs Computing, and Computing itself also requires Energy. Money can be thought of as stored work, stored energy. Money is power ... so to speak."},
  automator:  { label: "🦸‍♂️🦸‍♀️ Automator",  about: "The Automator is the superpower to automate things. In the world of bits and information it means creating programs that think by themselves. In the world of atoms, it goes further, having machines that do stuff on their own."},
  mover:      { label: "🦸‍♂️🦸‍♀️ Mover",      about: " The Mover is the superpower to move things. Either you move matter, tangible things in the world of atoms; or you move and distribute information. Bits."},
  portal:     { label: "🦸‍♂️🦸‍♀️ Portal",     about: "The Portal is the superpower to go back and forth between the real word, the world of atoms and the imagined world, the world of bits. The Internet of Things (IOT) give the ability to sense the real world - microphones to hear, cameras to see etc. - so that those measurements become information. 3D-Printing is additive manufacturing, how we turn information - a design - into reality."},
  link:       { label: "🦸‍♂️🦸‍♀️ Link",       about: "The Link is the superpower to overlay the two realms on one another. Virtual, Augmented and Mixed Reality gives the ability to create experiences that we sense as we would within feel the real world and to mix digital creatures of imagination with the world of atoms."},
  lifeforce:  { label: "🦸‍♂️🦸‍♀️ Lifeforce",  about: " The Life Force is the power to read and write information stored in living creatures, thereby altering what and how they do. Synthetic Biology gives the ability for both sequencing the genome and for gene-editing. It's like being able to read and write the Book of Life - even to copy and paste!"},
};

function PowerCard({ k }) {
  const { label, about } = POWERS[k] || {};
  const [open, setOpen] = useState(false);
  return (
    <Card className="border-muted/20">
      <CardHeader
        className="py-2 px-4 text-sm font-medium cursor-pointer flex justify-between items-center select-none"
        onClick={() => setOpen(!open)}
      >
        {label}
        <ChevronDown
          className={
            "h-4 w-4 transition-transform " + (open ? "rotate-180" : "")
          }
        />
      </CardHeader>
      {open && (
        <CardContent className="text-xs whitespace-pre-line leading-tight">
          {about}
        </CardContent>
      )}
    </Card>
  );
}

/* Technology cards (middle / right) */
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

// const realmColour = (r) =>
//   r === "bits"  ? "bg-red-50"
// : r === "atoms" ? "bg-blue-50"
// :                 "bg-purple-50";

function TechCard({ k, text }) {
  if (!k) return <div />;                   // placeholder (keeps grid shape)

  const { label, realm, span } = TECH[k] || {};
  return (
    <Card
      className={realmColour(realm) + " border-muted/20"}
      style={span === 2 ? { gridColumn: "span 2 / span 2" } : undefined}
    >
      <CardHeader className="py-2 px-4 text-sm font-medium" style={DARK_TEXT}>{label}</CardHeader>
      <CardContent className="text-xs whitespace-pre-line leading-tight" style={DARK_TEXT}>
        {text || "❌"}
      </CardContent>
    </Card>
  );
}

/* Row specification: [powerKey, [midKey, rightKey]] */
const ROWS = [
  ["power",      ["computing",      "energy"]            ],
  ["",           ["crypto",         null]                ], // double-width
  ["automator",  ["ai",             "robot"]             ],
  ["mover",      ["networks",       "transportation"]    ],
  ["portal",     ["threeDprinting", "iot"]               ],
  ["link",       ["arvr",           null]                ], // double-width
  ["lifeforce",  ["synbio",         null]                ], // double-width
];

/* ———————————————————————————————  main element ————————————————————————————— */

export default function Pathway() {
  /* parse JSON input */
  let details = {};
  try { details = JSON.parse(props.data || "{}"); } catch (_) {}

  return (
    <div className="flex flex-col gap-4 mt-2">
      {/* header bar */}
      <div className="flex justify-between items-center">
        <h2 className="text-lg font-semibold select-none">🛤️ Pathway</h2>
      </div>

      {/* realm banners row */}
      <div className="grid gap-4" style={THREE_COL_STYLE}>
        <div /> {/* spacer */}
        <RealmBanner
          label={"Imagined, Information, Digital\nWorld of ℹ Bits"}
          realm="bits"
        />
        <RealmBanner
          label={'Real, Physical, Tangible "Stuff"\nWorld of ⚛ Atoms'}
          realm="atoms"
        />
      </div>

      {/* remaining rows */}
      {ROWS.map(([powerKey, [midKey, rightKey]], i) => {
        const wide = TECH[midKey]?.span === 2;
        return (
          <div key={i} className="grid gap-4" style={THREE_COL_STYLE}>
            {/* left column */}
            {powerKey ? <PowerCard k={powerKey} /> : <div />}

            {/* middle column (always) */}
            <TechCard k={midKey} text={details[midKey]} />

            {/* right column only when needed */}
            {!wide && (
              rightKey
                ? <TechCard k={rightKey} text={details[rightKey]} />
                : <div />
            )}
          </div>
        );
      })}
    </div>
  );
}
