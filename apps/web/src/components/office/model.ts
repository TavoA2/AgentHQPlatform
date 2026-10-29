import type { Agent, AgentStatus } from "@/lib/types";

// Scene palette (hex for three.js); mirrors the CSS tokens in globals.css.
export const PALETTE = {
  floor: "#0b1226",
  platform: "#111b3d",
  furniture: "#1a2650",
  cyan: "#22d3ee",
  violet: "#a78bfa",
  orange: "#fb923c",
  blue: "#60a5fa",
  rose: "#fb7185",
  emerald: "#34d399",
  muted: "#53608f",
} as const;

export type Department = {
  key: string;
  label: string;
  accent: string;
  center: [number, number]; // x, z on the floor
  size: [number, number]; // width, depth
};

// Fixed floor plan. Agents are placed by their `department` from the API; an unknown
// department gets its own space so new agents always appear (never invented ones).
export const DEPARTMENTS: Department[] = [
  { key: "executive", label: "Executive", accent: PALETTE.violet, center: [0, -7], size: [8, 5] },
  { key: "engineering", label: "Engineering", accent: PALETTE.cyan, center: [-8, 2], size: [7, 7] },
  { key: "quality", label: "Quality", accent: PALETTE.orange, center: [8, 2], size: [7, 7] },
];

const OVERFLOW: [number, number][] = [
  [-8, 10],
  [8, 10],
  [-16, -6],
  [16, -6],
];

export function departmentsFor(agents: Agent[]): Department[] {
  const known = new Set(DEPARTMENTS.map((d) => d.key));
  const extra = [...new Set(agents.map((a) => a.department).filter((d) => !known.has(d)))];
  return [
    ...DEPARTMENTS,
    ...extra.map((key, i) => ({
      key,
      label: key.charAt(0).toUpperCase() + key.slice(1),
      accent: PALETTE.blue,
      center: OVERFLOW[i % OVERFLOW.length],
      size: [7, 5] as [number, number],
    })),
  ];
}

/**
 * Desk positions inside a department. Pairs are staggered along the screen's horizontal
 * axis (x - z for the isometric camera) so neighbouring agents never overlap on screen.
 */
export function deskPosition(dept: Department, index: number): [number, number] {
  const row = Math.floor(index / 2);
  const side = index % 2 === 0 ? -1 : 1;
  const [cx, cz] = dept.center;
  const count = 1 + Math.floor(index / 2);
  const x = cx + side * 1.6 + (row - (count - 1) / 2) * 0.4;
  const z = cz - side * 1.3 + row * 2.6;
  return [x, z];
}

export type Placement = { agent: Agent; dept: Department; desk: [number, number] };

export function placeAgents(agents: Agent[]): Placement[] {
  const depts = departmentsFor(agents);
  const counts = new Map<string, number>();
  return agents.map((agent) => {
    const dept = depts.find((d) => d.key === agent.department) ?? depts[0];
    const index = counts.get(dept.key) ?? 0;
    counts.set(dept.key, index + 1);
    return { agent, dept, desk: deskPosition(dept, index) };
  });
}

export type Visual = {
  pose: "standing" | "working";
  screen: string; // monitor color
  screenIntensity: number;
  indicator: "none" | "waiting" | "error" | "completed";
  bodyTint: string | null;
};

/**
 * The only mapping from backend state to visuals. `completedRecently` is set solely by a
 * real `execution_finished` (succeeded) event; nothing here is simulated.
 */
export function visualFor(status: AgentStatus, completedRecently: boolean): Visual {
  switch (status) {
    case "RUNNING":
      return { pose: "working", screen: PALETTE.cyan, screenIntensity: 2.2, indicator: "none", bodyTint: null };
    case "WAITING_APPROVAL":
      return { pose: "standing", screen: PALETTE.orange, screenIntensity: 1.6, indicator: "waiting", bodyTint: null };
    case "FAILED":
      return { pose: "standing", screen: PALETTE.rose, screenIntensity: 1.4, indicator: "error", bodyTint: PALETTE.rose };
    default:
      return {
        pose: "standing",
        screen: completedRecently ? PALETTE.emerald : PALETTE.blue,
        screenIntensity: completedRecently ? 2 : 0.5,
        indicator: completedRecently ? "completed" : "none",
        bodyTint: null,
      };
  }
}

export const AGENT_COLORS: Record<string, string> = {
  cio: PALETTE.violet,
  devops: PALETTE.cyan,
  software_engineer: PALETTE.blue,
  qa: PALETTE.orange,
};

export const COMPLETED_FLASH_MS = 3500;
