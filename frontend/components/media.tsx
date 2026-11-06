"use client";
/* eslint-disable @next/next/no-img-element -- remote ESPN assets with a local fallback */
import clsx from "clsx";
import { useState } from "react";

export function TeamLogo({ abbr, size = 28, className }: { abbr: string; size?: number; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <span style={{ width: size, height: size }} className={clsx("num inline-flex items-center justify-center rounded-full bg-elevated text-[10px] text-ink-2", className)}>
        {abbr.slice(0, 3)}
      </span>
    );
  }
  return (
    <img src={`https://a.espncdn.com/i/teamlogos/nba/500/${abbr.toLowerCase()}.png`} alt="" width={size} height={size} loading="lazy"
         onError={() => setFailed(true)} style={{ width: size, height: size }} className={clsx("object-contain", className)} />
  );
}

export function Headshot({ id, name, size = 44, className }: { id: string; name: string; size?: number; className?: string }) {
  const [failed, setFailed] = useState(false);
  const initials = name.split(" ").map((w) => w[0]).slice(0, 2).join("");
  return (
    <span style={{ width: size, height: size }} className={clsx("relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-elevated text-xs font-medium text-ink-2 ring-1 ring-line", className)}>
      {failed ? initials : (
        <img src={`https://a.espncdn.com/i/headshots/nba/players/full/${id}.png`} alt="" loading="lazy" onError={() => setFailed(true)}
             className="absolute inset-0 h-full w-full object-cover object-top" />
      )}
    </span>
  );
}
