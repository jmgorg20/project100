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
  aiNoteMore: ["If it shows realistic people, places or events made or changed by AI, turn on the platform's AI label when you post.",
    "Kung may makatotohanang tao, lugar o pangyayari na gawa o binago ng AI, i-on ang AI label ng platform pag nag-post ka."],
  held: ["This video was reported and is on hold while we check it. You cannot download it for now.",
    "Na-report ang video na ito at naka-hold habang tinitingnan namin. Hindi muna ito ma-download."],
  reportTitle: ["Report a video", "I-report ang isang video"],
  reportIntro: ["Saw a video made with AutoEdit that breaks the rules (someone else's work, harm to a child, hate, a private person shown without consent...)? Paste its link. A person reviews every report.",
    "May nakita kang video na gawa sa AutoEdit na labag sa patakaran (gawa ng iba, pananakit sa bata, hate, pribadong tao na walang pahintulot...)? I-paste ang link. Tao ang tumitingin sa bawat report."],
  reportLink: ["Link to the video", "Link ng video"],
  reportReason: ["What is wrong", "Ano ang mali"],
  reportDetails: ["Details (optional)", "Detalye (optional)"],
  reportEmail: ["Your email, if we may contact you (optional)", "Email mo, kung puwede ka naming kontakin (optional)"],
  reportSend: ["Send report", "Ipadala ang report"],
  reportThanks: ["Thank you. We will look at it soon.", "Salamat. Titingnan namin ito agad."],
  reportLinkHint: ["Report a video", "Mag-report ng video"],
  r_copyright: ["My work used without permission (copyright)", "Ginamit ang gawa ko nang walang pahintulot (copyright)"],
  r_child_safety: ["Harm to a child", "Pananakit o pang-aabuso sa bata"],
  r_violence: ["Violence or threats", "Karahasan o pagbabanta"],
  r_hate: ["Hate against a group", "Pagkamuhi sa isang grupo"],
  r_harassment: ["Bullying or harassment", "Pambu-bully o harassment"],
  r_privacy: ["Shows me or my private details without consent", "Ipinapakita ako o ang pribadong detalye ko nang walang pahintulot"],
  r_illegal: ["Something else illegal (scam, fake ID...)", "Iba pang ilegal (scam, pekeng ID...)"],
  r_spam: ["Spam", "Spam"],
  r_other: ["Something else", "Iba pa"],
  plansNotInApp: ["Plans cannot be bought in the Android app. Your plan and minutes work the same here.",
    "Hindi nabibili ang plan sa Android app. Pareho pa rin dito ang plan at minutes mo."],
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
  trialLeft: ["Free trial: {days} day(s) left", "Free trial: {days} araw na lang"],
  trialEndedTitle: ["Your free trial has ended", "Tapos na ang free trial mo"],
  needPlan: ["Choose a plan to make more videos. Your finished videos can still be downloaded.",
    "Pumili ng plan para makagawa pa ng video. Puwede pa ring i-download ang mga natapos."],
  paymentProblem: ["The last payment did not go through: update your card to keep your plan.",
    "Hindi pumasok ang huling bayad: i-update ang card para tuloy ang plan."],
  canceling: ["Your plan ends on {date}.", "Matatapos ang plan mo sa {date}."],
  minutesUsed: ["{used} of {limit} minutes used this month", "{used} sa {limit} minuto ang nagamit ngayong buwan"],
  perInterval: ["{price} a {interval}", "{price} kada {interval}"],
  month: ["month", "buwan"],
  year: ["year", "taon"],
  choosePlan: ["Choose", "Piliin"],
  currentPlan: ["Your plan", "Plan mo"],
  manageBilling: ["Card, receipts and cancelling", "Card, resibo at pag-cancel"],
  onlyManagers: ["Only an owner or admin of the workspace can change the plan.",
    "Owner o admin lang ng workspace ang puwedeng magpalit ng plan."],
  contactForPlan: ["Online payment is not open yet: contact us to get a plan.",
    "Wala pang online payment: kontakin kami para sa plan."],
  billingThanks: ["Thank you! Your plan is active.", "Salamat! Aktibo na ang plan mo."],
  billingCancelled: ["Payment cancelled: nothing was charged.", "Kinansela ang bayad: walang siningil."],
  payments: ["Payments", "Mga bayad"],
  seePlans: ["See plans", "Tingnan ang plans"],
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
