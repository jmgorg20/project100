// The app's words in English and Taglish. Every screen uses t("key"); a missing Taglish entry falls
// back to English (and the test checks there are none missing).

import { useSyncExternalStore } from "react";

export type Lang = "en" | "tl";

export const WORDS = {
  appName: ["AutoEdit", "AutoEdit"],
  tagline: ["Your video, edited for you.", "Ang video mo, na-edit na para sa'yo."],
  // auth
  email: ["Email", "Email"],
  password: ["Password", "Password"],
  name: ["Your name (optional)", "Pangalan mo (optional)"],
  inviteCode: ["Invite code", "Invite code"],
  signIn: ["Sign in", "Mag-sign in"],
  signUp: ["Create account", "Gumawa ng account"],
  signOut: ["Sign out", "Mag-sign out"],
  withGoogle: ["Continue with Google", "Tuloy gamit ang Google"],
  forgot: ["Forgot password?", "Nakalimutan ang password?"],
  noAccount: ["New here? Create an account", "Bago ka? Gumawa ng account"],
  haveAccount: ["Have an account? Sign in", "May account ka na? Mag-sign in"],
  checkEmail: ["Check your email: we sent you a link.", "Tingnan ang email mo: may pinadala kaming link."],
  checkEmailSpam: ["Not there? Look in Spam, or send it again.", "Wala? Tingnan sa Spam, o ipadala ulit."],
  resend: ["Send the link again", "Ipadala ulit ang link"],
  confirming: ["Confirming your email…", "Kinukumpirma ang email mo…"],
  newPassword: ["New password", "Bagong password"],
  setPassword: ["Save the new password", "I-save ang bagong password"],
  passwordSaved: ["Password changed. Sign in with the new one.", "Napalitan na. Mag-sign in gamit ang bago."],
  sendResetLink: ["Send me a reset link", "Padalhan ako ng reset link"],
  passwordHint: ["At least 10 characters. A short sentence is easy to remember.",
    "Kahit 10 characters. Madaling tandaan ang maikling pangungusap."],
  twoStep: ["Two-step sign-in", "Two-step sign-in"],
  enterCode: ["Enter the 6-digit code from your authenticator app (or a recovery code).",
    "I-type ang 6-digit code mula sa authenticator app (o recovery code)."],
  code: ["Code", "Code"],
  verify: ["Continue", "Tuloy"],
  signupsPaused: ["New sign-ups are paused for now.", "Naka-pause muna ang bagong sign-up."],
  inviteOnly: ["Sign-up is by invitation for now: enter your invite code.",
    "Invite-only muna ang sign-up: ilagay ang invite code mo."],
  agree: ["I agree to the Terms and the Privacy notice, and I may only upload videos I have the right to use.",
    "Sang-ayon ako sa Terms at Privacy notice, at mag-a-upload lang ako ng video na may karapatan akong gamitin."],
  // nav
  navNew: ["New", "Bago"],
  navHistory: ["My videos", "Mga video ko"],
  navAccount: ["Account", "Account"],
  // new video
  newTitle: ["New video", "Bagong video"],
  pickVideo: ["Choose your video", "Piliin ang video mo"],
  pickHelp: ["From your phone's gallery or files. Up to {mb} MB, {min} minutes.",
    "Mula sa gallery o files. Hanggang {mb} MB, {min} minuto."],
  addPhotos: ["Add photos (optional)", "Magdagdag ng photos (optional)"],
  style: ["Style", "Style"],
  formatLabel: ["Layout", "Layout"],
  formatAuto: ["Automatic (best for the style)", "Automatic (bagay sa style)"],
  instruction: ["Instructions (optional)", "Instructions (optional)"],
  instructionHint: ["e.g. Mabilis, big captions, cut the long pauses", "hal. Mabilis, malalaking caption, tanggalin ang mahabang pause"],
  project: ["Project", "Project"],
  noProject: ["No project", "Walang project"],
  newProject: ["+ New project", "+ Bagong project"],
  projectName: ["Project name", "Pangalan ng project"],
  start: ["Edit my video", "I-edit ang video ko"],
  uploading: ["Uploading… {pct}%", "Ina-upload… {pct}%"],
  pause: ["Pause", "I-pause"],
  resume: ["Continue upload", "Ituloy ang upload"],
  resumeHint: ["Paused. Pick the same file again any time to continue.",
    "Naka-pause. Piliin ulit ang parehong file para ituloy."],
  checking: ["Checking the file…", "Sinusuri ang file…"],
  minutesLeft: ["{left} of {total} minutes left this month", "{left} sa {total} minuto ang natitira ngayong buwan"],
  // job
  queued: ["Waiting for an editor…", "Naghihintay ng editor…"],
  running: ["Editing… {pct}%", "Ine-edit… {pct}%"],
  succeeded: ["Done!", "Tapos na!"],
  failed: ["It did not work", "Hindi gumana"],
  cancelled: ["Stopped", "Itinigil"],
  cancel: ["Stop", "Itigil"],
  download: ["Download video", "I-download ang video"],
  deleteNow: ["Delete now", "Burahin na"],
  deleteConfirm: ["Delete this video and its files now? This cannot be undone.",
    "Burahin na ang video at mga file nito? Hindi na maibabalik."],
  expiresIn: ["Kept for {time} more, then deleted automatically.", "Itatabi pa nang {time}, tapos kusang mabubura."],
  checksPassed: ["All checks passed", "Pasado lahat ng check"],
  checksWarn: ["Some checks need a look", "May ilang check na dapat tingnan"],
  storyboard: ["Storyboard", "Storyboard"],
  captions: ["Captions", "Captions"],
  editCaptions: ["Fix captions", "Ayusin ang captions"],
  saveRender: ["Save and make the video again", "I-save at gawin ulit ang video"],
  exportTitle: ["Export", "Export"],
  exportSize: ["Size", "Laki"],
  exportQuality: ["Quality", "Quality"],
  exportFps: ["Frames per second", "Frames per second"],
  exportStart: ["Make this version", "Gawin ang version na ito"],
  aiNote: ["Edited automatically with AI. Check it before you post.",
    "Na-edit nang automatic gamit ang AI. Tingnan muna bago i-post."],
  tryAgain: ["Try again", "Subukan ulit"],
  // history
  historyEmpty: ["No videos yet. Tap New to start.", "Wala pang video. Pindutin ang Bago para magsimula."],
  loadMore: ["Show more", "Ipakita pa"],
  allProjects: ["All projects", "Lahat ng project"],
  // account
  account: ["Account", "Account"],
  language: ["Language", "Wika"],
  usage: ["This month", "Ngayong buwan"],
  devices: ["Signed-in devices", "Mga naka-sign in na device"],
  thisDevice: ["this device", "itong device"],
  endOthers: ["Sign out the other devices", "I-sign out ang ibang device"],
  changePassword: ["Change password", "Palitan ang password"],
  currentPassword: ["Current password", "Kasalukuyang password"],
  saved: ["Saved.", "Na-save."],
  mfaOn: ["Two-step sign-in is on.", "Naka-on ang two-step sign-in."],
  mfaSetup: ["Turn on two-step sign-in", "I-on ang two-step sign-in"],
  mfaScan: ["Add this key to your authenticator app (Google Authenticator, Authy…), then enter its code.",
    "Idagdag ang key sa authenticator app mo, tapos i-type ang code."],
  mfaCodes: ["Your recovery codes (each works once). Keep them somewhere safe:",
    "Mga recovery code mo (isang beses lang bawat isa). Itago nang mabuti:"],
  mfaOff: ["Turn off two-step sign-in", "I-off ang two-step sign-in"],
  exportData: ["Download my data", "I-download ang data ko"],
  deleteAccount: ["Delete my account", "Burahin ang account ko"],
  deleteAccountWarn: ["This deletes your account, your workspace and all its videos now.",
    "Buburahin nito ngayon din ang account mo, workspace, at lahat ng video."],
  confirmWithPassword: ["Type your password to confirm", "I-type ang password para kumpirmahin"],
  organisation: ["Workspace", "Workspace"],
  members: ["Members", "Mga miyembro"],
  invite: ["Invite", "Imbitahan"],
  inviteSent: ["Invitation sent.", "Naipadala ang imbitasyon."],
  joinTitle: ["Join a workspace", "Sumali sa workspace"],
  join: ["Join", "Sumali"],
  plan: ["Plan and billing", "Plan at bayad"],
  planSoon: ["Plans and payment are coming soon. For now your workspace has {min} minutes a month.",
    "Malapit na ang plans at bayad. Sa ngayon may {min} minuto kada buwan ang workspace mo."],
  install: ["Install the app", "I-install ang app"],
  offline: ["You are offline. Your videos keep editing on our side; this page updates when you are back.",
    "Offline ka. Tuloy ang pag-edit sa amin; mag-a-update ito pagbalik ng internet."],
  updateReady: ["A new version is ready.", "May bagong version."],
  reload: ["Reload", "I-reload"],
  terms: ["Terms", "Terms"],
  privacy: ["Privacy", "Privacy"],
  loading: ["Loading…", "Naglo-load…"],
  back: ["Back", "Bumalik"],
  save: ["Save", "I-save"],
  close: ["Close", "Isara"],
} as const satisfies Record<string, readonly [string, string]>;

export type WordKey = keyof typeof WORDS;
const STORE = "autoedit.lang";
let lang: Lang = (() => {
  try {
    const saved = localStorage.getItem(STORE);
    if (saved === "en" || saved === "tl") return saved;
  } catch {
    // no storage
  }
  return "en";
})();
const listeners = new Set<() => void>();

export function setLang(next: Lang) {
  lang = next;
  try {
    localStorage.setItem(STORE, next);
  } catch {
    // no storage
  }
  document.documentElement.lang = next === "tl" ? "fil" : "en";
  listeners.forEach((l) => l());
}

export function getLang() {
  return lang;
}

export function useLang(): Lang {
  return useSyncExternalStore((cb) => {
    listeners.add(cb);
    return () => listeners.delete(cb);
  }, () => lang);
}

export function t(key: WordKey, values: Record<string, string | number> = {}): string {
  const text = WORDS[key][lang === "tl" ? 1 : 0] || WORDS[key][0];
  return text.replace(/\{(\w+)\}/g, (_, k: string) => String(values[k] ?? ""));
}

/** A name from the catalog in the current language. */
export function pick(item: { name: string; tl?: string }): string {
  return lang === "tl" && item.tl ? item.tl : item.name;
}

export function duration(seconds: number): string {
  if (seconds >= 86_400) return lang === "tl" ? `${Math.floor(seconds / 86_400)} araw` : `${Math.floor(seconds / 86_400)} days`;
  if (seconds >= 3600) return lang === "tl" ? `${Math.floor(seconds / 3600)} oras` : `${Math.floor(seconds / 3600)} hours`;
  return lang === "tl" ? `${Math.max(1, Math.floor(seconds / 60))} minuto` : `${Math.max(1, Math.floor(seconds / 60))} minutes`;
}
