import Image from "next/image";

interface Props {
  lastUpdated?: string;
}

export default function Header({ lastUpdated }: Props) {
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-canvas/85 backdrop-blur">
      <div className="h-[3px] w-full bg-accent" aria-hidden />
      <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-3 px-4 sm:px-6">
        <Image
          src="/gdg_logo.svg"
          alt="Google Developer Groups logo"
          width={88}
          height={50}
          priority
          className="h-10 w-[72px] shrink-0 object-contain sm:h-11 sm:w-[78px]"
        />
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
