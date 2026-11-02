/* Back navigation — phone hardware button, browser back, and the arrow.
 *
 * The app is a single page with no router, so the phone's back gesture used to
 * close the whole app instead of closing one screen. This module gives every
 * open layer (a screen, then a panel on top of it) one browser history entry.
 * Pressing back pops that entry and closes the layer.
 *
 * Nothing here is React-specific on purpose: App.jsx only tells it how many
 * layers are open and what "close the top one" means right now.
 */

let stack = []        // one close callback per open layer
let pending = 0       // backs we fired ourselves — do not handle them twice
let blocked = false   // a modal owns the screen: back must do nothing
let armed = false     // installed app (PWA / APK) keeps one spare entry

const installed = () =>
  typeof window !== 'undefined' &&
  (window.Capacitor != null ||
    window.navigator.standalone === true ||
    !!(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches))

export const depth = () => stack.length

/** A ringing alarm or a running check-in must survive a stray back press. */
export function setBlocked(v) {
  blocked = !!v
}

/** Keep history in step with the screen: one entry per open layer. */
export function sync(target, closeTop) {
  if (typeof window === 'undefined') return
  while (stack.length > target) {
    stack.pop()
    pending += 1          // the app already closed it; swallow the popstate
    window.history.back()
  }
  while (stack.length < target) {
    stack.push(closeTop)
    window.history.pushState({ saavren: stack.length }, '')
  }
}

/** The visible back arrow, and every in-app "close" that should feel like back. */
export function goBack() {
  if (blocked) return
  if (!stack.length) {
    // Nothing of ours to close. In a browser tab that means leave the page,
    // which is what a back button is supposed to do there.
    if (typeof window !== 'undefined') window.history.back()
    return
  }
  const close = stack.pop()
  pending += 1
  window.history.back()
  if (close) close()
}

/** One throwaway entry so the first back press in an installed app stays inside. */
export function arm() {
  if (armed || !installed()) return
  armed = true
  window.history.pushState({ saavren: 0 }, '')
}

export function handlePopState() {
  if (pending > 0) {
    pending -= 1
    return
  }
  if (blocked) {
    // Refuse, and put the entry back so the next press also lands here.
    window.history.pushState({ saavren: depth() }, '')
    return
  }
  const close = stack.pop()
  if (close) close()
  if (!stack.length && installed()) window.history.pushState({ saavren: 0 }, '')
}
