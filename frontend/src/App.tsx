import { HealthPanel } from './features/health/HealthPanel'
import { PatchReviewPanel } from './features/patches/PatchReviewPanel'
import { DeveloperWorkspace } from './features/workspace/DeveloperWorkspace'

export default function App() {
  return (
    <div className="mx-auto flex min-h-screen max-w-[1440px] flex-col px-4 sm:px-8 xl:px-10">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-stone-200 py-5">
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
        <nav
          aria-label="Workspace sections"
          className="flex items-center gap-4"
        >
          <a
            href="#workspace"
            className="text-sm text-stone-600 hover:text-stone-950"
          >
            Workspace
          </a>
          <a
            href="#patch-review"
            className="text-sm text-stone-600 hover:text-stone-950"
          >
            Patch review
          </a>
          <span className="rounded-full border border-stone-300 px-3 py-1 font-mono text-[10px] tracking-wide text-stone-600">
            DEVELOPER WORKSPACE
          </span>
        </nav>
      </header>
      <main className="flex-1 py-8 sm:py-12">
        <div className="mb-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-end">
          <div>
            <p className="mb-3 font-mono text-[11px] tracking-[0.22em] text-emerald-800 uppercase">
              Understand · propose · review · verify
            </p>
            <h1 className="max-w-3xl text-3xl leading-tight font-semibold tracking-tight sm:text-4xl">
              A grounded workspace for repository repair.
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-stone-600 sm:text-base">
              Explore immutable snapshots, investigate with cited evidence, and
              move proposed changes through human review and isolated checks.
            </p>
          </div>
          <HealthPanel />
        </div>
        <div id="workspace">
          <DeveloperWorkspace />
        </div>
        <div id="patch-review" className="mt-8 scroll-mt-6">
          <PatchReviewPanel />
        </div>
      </main>
      <footer className="flex flex-wrap justify-between gap-2 border-t border-stone-200 py-5 font-mono text-[10px] tracking-wide text-stone-500">
        <span>PATCHWORK AI</span>
        <span>SNAPSHOT-BOUND · HUMAN-REVIEWED · ISOLATED</span>
      </footer>
    </div>
  )
}
