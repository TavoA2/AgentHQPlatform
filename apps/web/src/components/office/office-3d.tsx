"use client";

// 3D isometric office (Sprint 4). Loaded with next/dynamic, so three.js is only downloaded
// when the 3D view is used. Built from primitives only: no external models or fonts.

import { Edges, Html, OrbitControls } from "@react-three/drei";
import { Canvas, type ThreeEvent, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import type { Agent } from "@/lib/types";
import {
  AGENT_COLORS,
  type Department,
  PALETTE,
  type Placement,
  departmentsFor,
  placeAgents,
  visualFor,
} from "./model";

export type Office3DProps = {
  agents: Agent[];
  completed: ReadonlySet<string>;
  selected: string | null;
  onSelect: (key: string | null) => void;
  onOpenBrain: () => void;
  animate: boolean;
};

const HOME_TARGET = new THREE.Vector3(0, 0, 0);
const HOME_CAMERA = new THREE.Vector3(19, 23, 19);
const PAN_LIMIT = 14;

function useTabVisible(): boolean {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const onChange = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
  return visible;
}

export default function Office3D(props: Office3DProps) {
  const visible = useTabVisible();
  return (
    <Canvas
      // Rendering stops entirely while the tab is hidden.
      frameloop={visible ? "always" : "never"}
      dpr={[1, 1.5]}
      camera={{ position: HOME_CAMERA.toArray(), fov: 35, near: 0.1, far: 200 }}
      onPointerMissed={() => props.onSelect(null)}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      aria-label="3D office"
    >
      <color attach="background" args={[PALETTE.floor]} />
      <fog attach="fog" args={[PALETTE.floor, 34, 70]} />
      <Scene {...props} />
    </Canvas>
  );
}

function Scene({ agents, completed, selected, onSelect, onOpenBrain, animate }: Office3DProps) {
  const placements = useMemo(() => placeAgents(agents), [agents]);
  const departments = useMemo(() => departmentsFor(agents), [agents]);
  // Focus requests: a clicked department (handler) or the selected agent's department.
  const [deptFocus, setDeptFocus] = useState<{ key: string; point: [number, number] } | null>(null);
  const selectedPlacement = placements.find((p) => p.agent.key === selected);
  const agentFocus = selectedPlacement
    ? { key: `agent:${selectedPlacement.agent.key}`, point: selectedPlacement.dept.center }
    : null;

  return (
    <>
      <ambientLight intensity={0.35} />
      <hemisphereLight args={["#8fb3ff", PALETTE.floor, 0.5]} />
      <directionalLight position={[10, 18, 8]} intensity={0.7} />
      <pointLight position={[0, 4, 0]} color={PALETTE.violet} intensity={18} distance={14} />

      <Floor />
      {departments.map((d) => (
        <DepartmentSpace
          key={d.key}
          dept={d}
          onFocus={() => setDeptFocus({ key: `dept:${d.key}:${Date.now()}`, point: d.center })}
        />
      ))}
      <MeetingArea />
      <Brain animate={animate} onOpen={onOpenBrain} />
      {placements.map((p) => (
        <Workstation
          key={p.agent.key}
          placement={p}
          selected={p.agent.key === selected}
          completedRecently={completed.has(p.agent.key)}
          animate={animate}
          onSelect={() => onSelect(p.agent.key)}
        />
      ))}
      <CameraRig requests={[deptFocus, agentFocus]} animate={animate} />
    </>
  );
}

type FocusRequest = { key: string; point: [number, number] } | null;

function CameraRig({ requests, animate }: { requests: FocusRequest[]; animate: boolean }) {
  const controls = useRef<React.ComponentRef<typeof OrbitControls>>(null);
  const camera = useThree((s) => s.camera);
  const seen = useRef(new Set<string>());
  const goal = useRef<THREE.Vector3 | null>(null);

  useFrame((_, delta) => {
    const c = controls.current;
    if (!c) return;
    // Keep panning inside the building.
    c.target.x = THREE.MathUtils.clamp(c.target.x, -PAN_LIMIT, PAN_LIMIT);
    c.target.z = THREE.MathUtils.clamp(c.target.z, -PAN_LIMIT, PAN_LIMIT);
    c.target.y = 0;
    // Any request with a key not seen before becomes the new camera goal.
    for (const r of requests) {
      if (r && !seen.current.has(r.key)) {
        seen.current.add(r.key);
        goal.current = new THREE.Vector3(r.point[0], 0, r.point[1]);
      }
    }
    const focus = goal.current;
    if (!focus) return;
    // Smoothly glide the camera to the focused department (instant with reduced motion).
    const t = animate ? 1 - Math.exp(-delta * 3) : 1;
    const offset = camera.position.clone().sub(c.target);
    c.target.lerp(focus, t);
    camera.position.copy(c.target.clone().add(offset));
    if (c.target.distanceTo(focus) < 0.05) goal.current = null;
    c.update();
  });

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      target={HOME_TARGET}
      enableDamping={animate}
      minDistance={12}
      maxDistance={42}
      minPolarAngle={0.45}
      maxPolarAngle={1.15}
      screenSpacePanning={false}
    />
  );
}

function Floor() {
  return (
    <group>
      <mesh rotation-x={-Math.PI / 2} position-y={-0.01}>
        <planeGeometry args={[60, 60]} />
        <meshStandardMaterial color={PALETTE.floor} roughness={0.95} />
      </mesh>
      <gridHelper args={[60, 30, "#1b2a5a", "#131e45"]} position-y={0} />
    </group>
  );
}

function DepartmentSpace({ dept, onFocus }: { dept: Department; onFocus: () => void }) {
  const [x, z] = dept.center;
  const [w, d] = dept.size;
  const [hovered, setHovered] = useState(false);
  return (
    <group position={[x, 0, z]}>
      <mesh
        position-y={0.06}
        onClick={(e: ThreeEvent<MouseEvent>) => {
          e.stopPropagation();
          onFocus();
        }}
        onPointerOver={() => setHovered(true)}
        onPointerOut={() => setHovered(false)}
      >
        <boxGeometry args={[w, 0.12, d]} />
        <meshStandardMaterial color={PALETTE.platform} roughness={0.8} />
        <Edges color={dept.accent} lineWidth={hovered ? 2.5 : 1.5} />
      </mesh>
      {/* Low back wall with a neon strip gives each department a room-like corner. */}
      <mesh position={[0, 0.7, -d / 2 + 0.06]}>
        <boxGeometry args={[w, 1.4, 0.12]} />
        <meshStandardMaterial color={PALETTE.furniture} />
      </mesh>
      <mesh position={[0, 1.42, -d / 2 + 0.13]}>
        <boxGeometry args={[w * 0.9, 0.04, 0.02]} />
        <meshStandardMaterial color={dept.accent} emissive={dept.accent} emissiveIntensity={2.5} />
      </mesh>
      {/* Label on the front-left edge, so desks and name tags never cover it. */}
      <Html position={[-w / 2 + 0.2, 0.25, d / 2]} center className="pointer-events-none select-none">
        <span
          className="whitespace-nowrap rounded border px-2 py-0.5 font-mono text-[11px] uppercase tracking-widest"
          style={{ borderColor: dept.accent, color: dept.accent, background: "rgba(7,11,26,.75)" }}
        >
          {dept.label}
        </span>
      </Html>
    </group>
  );
}

function MeetingArea() {
  return (
    <group position={[0, 0, 7]}>
      <mesh position-y={0.4}>
        <cylinderGeometry args={[1.3, 1.3, 0.08, 24]} />
        <meshStandardMaterial color={PALETTE.furniture} />
        <Edges color={PALETTE.blue} />
      </mesh>
      <mesh position-y={0.2}>
        <cylinderGeometry args={[0.15, 0.25, 0.4, 12]} />
        <meshStandardMaterial color={PALETTE.platform} />
      </mesh>
      {[0, 1, 2, 3, 4].map((i) => {
        const a = (i / 5) * Math.PI * 2;
        return (
          <mesh key={i} position={[Math.cos(a) * 1.8, 0.22, Math.sin(a) * 1.8]}>
            <cylinderGeometry args={[0.25, 0.25, 0.44, 10]} />
            <meshStandardMaterial color={PALETTE.platform} />
          </mesh>
        );
      })}
    </group>
  );
}

function Brain({ animate, onOpen }: { animate: boolean; onOpen: () => void }) {
  const shell = useRef<THREE.Mesh>(null);
  const core = useRef<THREE.Mesh>(null);
  const [hovered, setHovered] = useState(false);
  useFrame((state, delta) => {
    if (!animate) return;
    if (shell.current) {
      shell.current.rotation.y += delta * 0.25;
      shell.current.rotation.x += delta * 0.1;
    }
    if (core.current) {
      const pulse = 1 + Math.sin(state.clock.elapsedTime * 1.6) * 0.06;
      core.current.scale.setScalar(pulse);
    }
  });
  return (
    <group
      position={[0, 0, 0]}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation();
        onOpen();
      }}
      onPointerOver={() => setHovered(true)}
      onPointerOut={() => setHovered(false)}
    >
      <mesh position-y={0.3}>
        <cylinderGeometry args={[1.4, 1.7, 0.6, 6]} />
        <meshStandardMaterial color={PALETTE.platform} />
        <Edges color={PALETTE.violet} />
      </mesh>
      <mesh ref={shell} position-y={2.2}>
        <icosahedronGeometry args={[1.25, 1]} />
        <meshStandardMaterial
          color={PALETTE.violet}
          emissive={PALETTE.violet}
          emissiveIntensity={hovered ? 1.6 : 0.9}
          wireframe
        />
      </mesh>
      <mesh ref={core} position-y={2.2}>
        <icosahedronGeometry args={[0.6, 2]} />
        <meshStandardMaterial
          color={PALETTE.cyan}
          emissive={PALETTE.cyan}
          emissiveIntensity={hovered ? 3 : 2}
          flatShading
        />
      </mesh>
      <Html position={[0, 3.9, 0]} center className="pointer-events-none select-none">
        <span className="whitespace-nowrap rounded border border-violet/60 bg-background/80 px-2 py-0.5 font-mono text-[11px] uppercase tracking-widest text-violet">
          The Brain
        </span>
      </Html>
    </group>
  );
}

function Workstation({
  placement,
  selected,
  completedRecently,
  animate,
  onSelect,
}: {
  placement: Placement;
  selected: boolean;
  completedRecently: boolean;
  animate: boolean;
  onSelect: () => void;
}) {
  const { agent, desk } = placement;
  const visual = visualFor(agent.status, completedRecently);
  const color = AGENT_COLORS[agent.key] ?? PALETTE.blue;
  const screen = useRef<THREE.MeshStandardMaterial>(null);

  useFrame((state) => {
    if (!animate || !screen.current) return;
    // A working screen flickers gently; others hold steady.
    screen.current.emissiveIntensity =
      visual.pose === "working"
        ? visual.screenIntensity * (0.85 + Math.sin(state.clock.elapsedTime * 9) * 0.15)
        : visual.screenIntensity;
  });

  return (
    <group position={[desk[0], 0.12, desk[1]]}>
      {/* Desk and monitor face the camera side (+z). */}
      <mesh position={[0, 0.72, -0.2]}>
        <boxGeometry args={[1.6, 0.08, 0.8]} />
        <meshStandardMaterial color={PALETTE.furniture} />
      </mesh>
      <mesh position={[0, 0.36, -0.2]}>
        <boxGeometry args={[1.4, 0.72, 0.6]} />
        <meshStandardMaterial color={PALETTE.platform} />
      </mesh>
      <mesh position={[0, 1.15, -0.45]}>
        <boxGeometry args={[0.9, 0.55, 0.05]} />
        <meshStandardMaterial
          ref={screen}
          color={visual.screen}
          emissive={visual.screen}
          emissiveIntensity={visual.screenIntensity}
        />
      </mesh>
      <mesh position={[0, 0.25, 0.75]}>
        <boxGeometry args={[0.55, 0.45, 0.55]} />
        <meshStandardMaterial color={PALETTE.furniture} />
      </mesh>
      <Character
        color={visual.bodyTint ?? color}
        pose={visual.pose}
        animate={animate}
        selected={selected}
        onSelect={onSelect}
      />
      <Indicator kind={visual.indicator} animate={animate} />
      <Html position={[0, 2.35, 0.75]} center className="pointer-events-none select-none">
        <span
          className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] ${selected ? "bg-cyan text-background" : "bg-background/80 text-foreground"}`}
        >
          {agent.display_name}
        </span>
      </Html>
    </group>
  );
}

function Character({
  color,
  pose,
  animate,
  selected,
  onSelect,
}: {
  color: string;
  pose: "standing" | "working";
  animate: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  const body = useRef<THREE.Group>(null);
  // Working: seated on the stool facing the screen. Standing: beside the desk.
  const base = pose === "working" ? new THREE.Vector3(0, 0.25, 0.75) : new THREE.Vector3(1.15, 0, 0.55);

  useFrame((state) => {
    if (!body.current) return;
    const t = state.clock.elapsedTime;
    body.current.position.copy(base);
    if (!animate) return;
    if (pose === "working") {
      body.current.position.y = base.y + Math.abs(Math.sin(t * 8)) * 0.03; // typing
    } else {
      body.current.rotation.y = Math.sin(t * 0.8) * 0.25; // idle sway
    }
  });

  return (
    <group
      ref={body}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation();
        onSelect();
      }}
      onPointerOver={() => (document.body.style.cursor = "pointer")}
      onPointerOut={() => (document.body.style.cursor = "")}
    >
      <mesh position-y={0.75}>
        <capsuleGeometry args={[0.24, 0.55, 4, 10]} />
        <meshStandardMaterial color={color} roughness={0.5} />
      </mesh>
      <mesh position-y={1.38}>
        <sphereGeometry args={[0.2, 16, 12]} />
        <meshStandardMaterial color="#e6ebff" roughness={0.4} />
      </mesh>
      <mesh position-y={1.4} position-z={0.17}>
        <boxGeometry args={[0.24, 0.06, 0.04]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1.5} />
      </mesh>
      {selected && (
        <mesh rotation-x={-Math.PI / 2} position-y={0.02}>
          <ringGeometry args={[0.45, 0.6, 32]} />
          <meshBasicMaterial color={PALETTE.cyan} />
        </mesh>
      )}
    </group>
  );
}

function Indicator({ kind, animate }: { kind: ReturnType<typeof visualFor>["indicator"]; animate: boolean }) {
  const ref = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (!ref.current || !animate) return;
    const t = state.clock.elapsedTime;
    ref.current.position.y = 2.9 + Math.sin(t * 2.5) * 0.12;
    if (kind === "completed") ref.current.rotation.y += 0.05;
  });
  if (kind === "none") return null;
  const color = kind === "waiting" ? PALETTE.orange : kind === "error" ? PALETTE.rose : PALETTE.emerald;
  return (
    <group ref={ref} position={[1.15, 2.9, 0.55]}>
      {kind === "waiting" && (
        <>
          <mesh position-y={0.18}>
            <boxGeometry args={[0.12, 0.42, 0.12]} />
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2} />
          </mesh>
          <mesh position-y={-0.15}>
            <boxGeometry args={[0.12, 0.12, 0.12]} />
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2} />
          </mesh>
        </>
      )}
      {kind === "error" &&
        [Math.PI / 4, -Math.PI / 4].map((r) => (
          <mesh key={r} rotation-z={r}>
            <boxGeometry args={[0.12, 0.55, 0.12]} />
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2} />
          </mesh>
        ))}
      {kind === "completed" && (
        <mesh rotation-x={Math.PI / 2}>
          <torusGeometry args={[0.3, 0.06, 8, 24]} />
          <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2.5} />
        </mesh>
      )}
    </group>
  );
}
