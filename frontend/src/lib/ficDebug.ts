/**
 * Lightweight dev-only diagnostic helper.
 * All exports are no-ops when import.meta.env.DEV is false — zero production overhead.
 */

const DEV = import.meta.env.DEV;

interface DebugCounters {
  mounts: Record<string, number>;
  unmounts: Record<string, number>;
  activeModals: string[];
  listenersAttached: number;
  listenersRemoved: number;
}

const _c: DebugCounters = {
  mounts: {},
  unmounts: {},
  activeModals: [],
  listenersAttached: 0,
  listenersRemoved: 0,
};

function _imgCount(): number {
  return document.querySelectorAll('img').length;
}

function printSummary(): void {
  const active: Record<string, number> = {};
  for (const [k, v] of Object.entries(_c.mounts)) {
    const diff = v - (_c.unmounts[k] ?? 0);
    if (diff !== 0) active[k] = diff;
  }
  const listenerLeak = _c.listenersAttached - _c.listenersRemoved;
  console.group('[ficDebug] Summary');
  console.log('Active mounts (net):', active);
  console.log('Open modals:', _c.activeModals.slice());
  console.log('img elements in DOM:', _imgCount());
  console.log('Listeners attached (lifetime):', _c.listenersAttached);
  console.log('Listeners removed (lifetime):', _c.listenersRemoved);
  console.log(
    listenerLeak > 0 ? '%c⚠ Listener leak estimate: ' + listenerLeak : 'Listener leak estimate: ' + listenerLeak,
    listenerLeak > 0 ? 'color: orange; font-weight: bold' : '',
  );
  console.groupEnd();
}

export const ficDebug = {
  mount(name: string): void {
    if (!DEV) return;
    _c.mounts[name] = (_c.mounts[name] ?? 0) + 1;
    console.debug(`[ficDebug] mount: ${name} (lifetime: ${_c.mounts[name]})`);
  },

  unmount(name: string): void {
    if (!DEV) return;
    _c.unmounts[name] = (_c.unmounts[name] ?? 0) + 1;
    const active = (_c.mounts[name] ?? 0) - _c.unmounts[name];
    console.debug(`[ficDebug] unmount: ${name} (still mounted: ${active})`);
  },

  modalOpen(name: string): void {
    if (!DEV) return;
    _c.activeModals.push(name);
    console.debug(`[ficDebug] modalOpen: ${name} (total open: ${_c.activeModals.length})`);
  },

  modalClose(name: string): void {
    if (!DEV) return;
    const idx = _c.activeModals.lastIndexOf(name);
    if (idx !== -1) _c.activeModals.splice(idx, 1);
    console.debug(`[ficDebug] modalClose: ${name} (total open: ${_c.activeModals.length})`);
  },

  dragStart(name: string): void {
    if (!DEV) return;
    console.debug(`[ficDebug] dragStart: ${name}`);
  },

  dragEnd(name: string): void {
    if (!DEV) return;
    console.debug(`[ficDebug] dragEnd: ${name}`);
  },

  /** Call once per window.addEventListener to track attach count. */
  listenerAttach(name: string): void {
    if (!DEV) return;
    _c.listenersAttached++;
    console.debug(`[ficDebug] listener+: ${name} (total: ${_c.listenersAttached}, net: ${_c.listenersAttached - _c.listenersRemoved})`);
  },

  /** Call once per window.removeEventListener to track remove count. */
  listenerRemove(name: string): void {
    if (!DEV) return;
    _c.listenersRemoved++;
    const net = _c.listenersAttached - _c.listenersRemoved;
    if (net < 0) {
      console.warn(`[ficDebug] listener-: ${name} — net is NEGATIVE (${net}), double-remove?`);
    } else {
      console.debug(`[ficDebug] listener-: ${name} (total removed: ${_c.listenersRemoved}, net: ${net})`);
    }
  },

  log(msg: string, ...args: unknown[]): void {
    if (!DEV) return;
    console.debug(`[ficDebug] ${msg}`, ...args);
  },

  printSummary,
};

// Expose on window so you can run window.__ficDebug.printSummary() in the DevTools console.
if (DEV) {
  (window as unknown as Record<string, unknown>).__ficDebug = {
    counters: _c,
    imgCount: _imgCount,
    printSummary,
    ficDebug,
  };
}
