interface Props {
  value: number;
  label: string;
  tone?: "light" | "dark";
  className?: string;
}

export default function ProgressBar({ value, label, tone = "light", className = "" }: Props) {
  const boundedValue = Math.max(0, Math.min(100, value));
  const track = tone === "dark" ? "bg-white/25" : "bg-black/10";
  const fill = tone === "dark" ? "bg-accent" : boundedValue >= 100 ? "bg-ink" : "bg-accent";
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(boundedValue)}
      className={`h-1.5 w-full overflow-hidden rounded-[2px] ${track} ${className}`}
    >
      <div className={`h-full rounded-[2px] transition-[width] duration-200 ${fill}`} style={{ width: `${boundedValue}%` }} />
    </div>
  );
}
