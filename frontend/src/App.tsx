import { HealthPanel } from './features/health/HealthPanel'

export default function App() {
  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-6 sm:px-10">
      <header className="flex items-center justify-between gap-4 border-b border-stone-200 py-7">
        <a
          className="flex items-center gap-3 font-semibold tracking-tight"
          href="/"
          aria-label="Patchwork AI home"
        >
          <span
            aria-hidden="true"
            className="grid grid-cols-2 gap-1 rounded-lg bg-stone-900 p-2"
          >
            <span className="size-2 rounded-sm bg-emerald-300" />
            <span className="size-2 rounded-sm bg-stone-100" />
            <span className="size-2 rounded-sm bg-stone-100" />
            <span className="size-2 rounded-sm bg-emerald-300" />
          </span>
          Patchwork <span className="font-normal text-stone-500">AI</span>
        </a>
        <span className="rounded-full border border-stone-300 px-3 py-1 font-mono text-xs text-stone-600">
          Foundation
        </span>
      </header>
      <main className="flex-1 py-14 sm:py-20">
        <p className="mb-5 font-mono text-xs tracking-widest text-stone-500 uppercase">
          System overview / 01
        </p>
        <h1 className="max-w-2xl text-4xl leading-tight font-semibold tracking-tight sm:text-5xl">
          Better fixes begin
          <br />
          with clear evidence.
        </h1>
        <p className="mt-5 max-w-xl text-base leading-7 text-stone-600">
          A workspace for code investigation and verified repair. The foundation
          is here: a connected interface, a typed API, and local persistence.
        </p>
        <HealthPanel />
        <aside className="mt-8 border-l-2 border-stone-300 pl-5">
          <h2 className="text-sm font-medium">Next: repository intake</h2>
          <p className="mt-2 max-w-xl text-sm leading-6 text-stone-500">
            Repository import, AI investigation, and isolated test execution are
            planned for later milestones.
          </p>
        </aside>
      </main>
      <footer className="flex flex-wrap justify-between gap-2 border-t border-stone-200 py-6 font-mono text-xs text-stone-500">
        <span>PATCHWORK AI</span>
        <span>Milestone 01 · Foundation</span>
      </footer>
    </div>
  )
}
