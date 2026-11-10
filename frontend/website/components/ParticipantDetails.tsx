"use client";

import { useEffect, useRef } from "react";
import { Check, ExternalLink, Mail, X } from "lucide-react";
import type { Badge, Participant } from "@/lib/types";
import { formatDate, initials } from "@/lib/format";
import ProgressBar from "./ProgressBar";

interface Props {
  participant: Participant;
  badges: Badge[];
  onClose: () => void;
}

export default function ParticipantDetails({ participant, badges, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  const pending = Math.max(0, participant.total - participant.completed);
  return (
    <div className="fixed inset-0 z-50">
      <div className="anim-fade absolute inset-0 bg-ink/50" onClick={onClose} aria-hidden />
      <aside role="dialog" aria-modal="true" aria-label={`${participant.name} details`} className="anim-drawer absolute right-0 top-0 flex h-full w-full max-w-md flex-col bg-white shadow-pop">
        <div className="h-[3px] w-full shrink-0 bg-accent" aria-hidden />
        <div className="flex items-start gap-3 border-b border-line p-4 sm:p-5">
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-sm bg-ink text-lg font-semibold text-white">{initials(participant.name)}</span>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold leading-tight">{participant.name}</h2>
            <div className="mt-1.5 flex flex-col gap-1 text-sm">
              {participant.email && <a href={`mailto:${participant.email}`} className="inline-flex items-center gap-1.5 truncate text-soft hover:text-ink hover:underline"><Mail className="h-3.5 w-3.5 shrink-0" aria-hidden /><span className="truncate">{participant.email}</span></a>}
              {participant.profileUrl && (
                <a href={participant.profileUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 font-medium text-accent-deep hover:underline">
                  <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden />Google Skills profile
                </a>
              )}
            </div>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close details" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm text-soft hover:bg-canvas hover:text-ink"><X className="h-5 w-5" /></button>
        </div>

        <div className="grid grid-cols-3 gap-2 p-4 sm:p-5 sm:pb-3">
          {[
            { label: "Rank", value: `#${participant.rank}`, hot: true },
            { label: "Completed", value: String(participant.completed), hot: false },
            { label: "Pending", value: String(pending), hot: false },
          ].map((item) => (
            <div key={item.label} className={`rounded-lg p-3 ${item.hot ? "bg-accent text-ink" : "bg-canvas"}`}>
              <p className="text-xl font-semibold tabular-nums leading-none">{item.value}</p>
              <p className={`mt-1.5 text-[11px] font-semibold uppercase tracking-wider ${item.hot ? "text-ink/80" : "text-faint"}`}>{item.label}</p>
            </div>
          ))}
        </div>

        <div className="px-4 pb-4 sm:px-5">
          <div className="mb-1.5 flex items-baseline justify-between text-sm">
            <span className="font-medium">Overall progress</span>
            <span className="tabular-nums text-soft">{participant.completed}/{participant.total} · {Math.round(participant.progress)}%</span>
          </div>
          <ProgressBar value={participant.progress} label="Overall progress" />
        </div>

        <h3 className="border-t border-line px-4 pb-2 pt-4 text-[11px] font-semibold uppercase tracking-wider text-faint sm:px-5">Badges</h3>
        <ul className="thin-scroll min-h-0 flex-1 divide-y divide-line overflow-y-auto px-4 pb-6 sm:px-5">
          {badges.map((badge) => {
            const status = participant.badges.find((item) => item.badgeKey === badge.key);
            const earned = status?.earned ?? false;
            const link = status?.url ?? badge.url;
            return (
              <li key={badge.key} className="flex items-center gap-3 py-3">
                {earned ? (
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent text-ink" aria-hidden><Check className="h-3.5 w-3.5" strokeWidth={3} /></span>
                ) : <span className="h-6 w-6 shrink-0 rounded-full border-2 border-[#CFCFCF]" aria-hidden />}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium leading-snug">{badge.name}</p>
                  <p className={`text-xs ${earned ? "text-soft" : "text-faint"}`}>{earned ? (status?.earnedDate ? `Earned ${formatDate(status.earnedDate)}` : "Earned") : "Pending"}</p>
                </div>
                {link && <a href={link} target="_blank" rel="noopener noreferrer" aria-label={`Open lab: ${badge.name}`} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-sm text-faint hover:bg-canvas hover:text-ink"><ExternalLink className="h-4 w-4" /></a>}
              </li>
            );
          })}
          {badges.length === 0 && <li className="py-4 text-sm text-faint">No verified badge mappings are available yet.</li>}
        </ul>
      </aside>
    </div>
  );
}
