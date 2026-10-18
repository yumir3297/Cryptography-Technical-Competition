/// <reference types="vite/client" />

// ``vite.config.ts`` runs in Node and reads one environment variable.  That is the
// only Node global this project touches, so it is declared here rather than pulling
// in the whole ``@types/node`` surface.
declare const process: { env: Record<string, string | undefined> }

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}

interface ImportMetaEnv {
  readonly VITE_VIEWER_KEY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
