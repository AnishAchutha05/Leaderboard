interface Props {
  lastUpdated?: string;
}

export default function Header({ lastUpdated }: Props) {
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-canvas/85 backdrop-blur">
      <div className="h-[3px] w-full bg-accent" aria-hidden />
      <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-3 px-4 sm:px-6">
        <div
          className="flex h-10 w-[104px] shrink-0 items-center justify-center rounded-sm border border-dashed border-faint text-[10px] font-semibold tracking-wider text-faint sm:h-11 sm:w-[132px] sm:text-[11px]"
          aria-label="GDG logo placeholder"
        >
          [ GDG LOGO ]
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold leading-tight sm:text-base">Google Skills Leaderboard</p>
          <p className="truncate text-[11px] leading-tight text-faint sm:text-xs">
            Track. Learn. Achieve.<span className="hidden sm:inline"> · GDG on Campus · JSSATE-B</span>
          </p>
        </div>
        {lastUpdated && (
          <p className="hidden text-right text-xs leading-tight text-faint md:block">
            <span className="block text-[10px] font-semibold uppercase tracking-wider">Last updated</span>
            <span className="tabular-nums text-soft">{lastUpdated}</span>
          </p>
        )}
      </div>
    </header>
  );
}
