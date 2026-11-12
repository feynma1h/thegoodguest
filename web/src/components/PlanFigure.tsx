"use client";

/**
 * A room's measured floor plan, drawn as SVG: the calling card's own plan
 * (lib/card/layout.layoutPlan), so a room looks the same wherever its plan
 * appears and every number on it is a measurement for the reasons the card
 * gives. The house draws one on each ready room's card; the returning home
 * draws the newest room's on its stage (decision 0361).
 *
 * The plan is laid out once in a fixed virtual frame and the SVG scales it,
 * so the callout keeps its proportion to the room at any size. Glows are the
 * card's window light (paint.ts's three stops), clipped to the floor.
 */

import { useId, useMemo } from "react";

import { layoutPlan, type CardOp } from "@/lib/card/layout";
import type { RoomMeasure } from "@/lib/card/measure";
import { alpha } from "@/lib/card/palette";

const VIEW = { w: 760, h: 480 };

const pts = (points: [number, number][]) =>
  points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");

export default function PlanFigure({
  measure,
  label,
  className,
  inset = 66,
}: {
  measure: RoomMeasure;
  /** What the drawing says to someone who can't see it. */
  label: string;
  className?: string;
  /** Room left around the plan for its dimension callout, in frame pixels. */
  inset?: number;
}) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const ops = useMemo(
    () => layoutPlan(measure, { x: 0, y: 0, w: VIEW.w, h: VIEW.h }, inset).ops,
    [measure, inset],
  );

  const render = (op: CardOp, i: number) => {
    switch (op.kind) {
      case "fill":
        return <polygon key={i} points={pts(op.points)} fill={op.fill} />;
      // Line weights are the card's, in screen pixels: a plan drawn small on
      // a house card keeps walls that read as walls.
      case "stroke":
        return op.closed ? (
          <polygon
            key={i}
            points={pts(op.points)}
            fill="none"
            stroke={op.stroke}
            strokeWidth={op.width}
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        ) : (
          <polyline
            key={i}
            points={pts(op.points)}
            fill="none"
            stroke={op.stroke}
            strokeWidth={op.width}
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
        );
      case "glow":
        return (
          <g key={i} clipPath={`url(#${uid}-c${i})`}>
            <defs>
              <clipPath id={`${uid}-c${i}`}>
                <polygon points={pts(op.clip)} />
              </clipPath>
              <radialGradient id={`${uid}-g${i}`}>
                <stop offset="0" stopColor={alpha(op.color, 0.24)} />
                <stop offset="0.55" stopColor={alpha(op.color, 0.09)} />
                <stop offset="1" stopColor={alpha(op.color, 0)} />
              </radialGradient>
            </defs>
            <circle cx={op.at[0]} cy={op.at[1]} r={op.radius} fill={`url(#${uid}-g${i})`} />
          </g>
        );
      case "text":
        return (
          <text
            key={i}
            x={op.at[0]}
            y={op.at[1]}
            fill={op.fill}
            fontFamily="var(--font-jetbrains-mono), ui-monospace, monospace"
            fontSize={op.size + 4}
            fontWeight={op.weight}
            letterSpacing={`${op.tracking}em`}
            textAnchor={op.align === "center" ? "middle" : op.align === "right" ? "end" : "start"}
            dominantBaseline="middle"
            transform={op.rotateDeg ? `rotate(${op.rotateDeg} ${op.at[0]} ${op.at[1]})` : undefined}
          >
            {op.text}
          </text>
        );
      default:
        // The plan carries no wordmark and no background of its own.
        return null;
    }
  };

  return (
    <svg
      viewBox={`0 0 ${VIEW.w} ${VIEW.h}`}
      role="img"
      aria-label={label}
      className={className}
      preserveAspectRatio="xMidYMid meet"
    >
      {ops.map(render)}
    </svg>
  );
}
