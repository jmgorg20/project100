// Is the web app running inside the AutoEdit Android app (a Trusted Web Activity)? The app opens
// /app/?source=android; Chrome also sends an android-app:// referrer. Remembered for this tab only
// (sessionStorage): the same phone's Chrome shares localStorage with the app, and there the
// website must behave as the website.
const KEY = "autoedit.platform";

export function inAndroidApp(): boolean {
  try {
    if (new URLSearchParams(window.location.search).get("source") === "android" || document.referrer.startsWith("android-app://")) {
      sessionStorage.setItem(KEY, "android");
    }
    return sessionStorage.getItem(KEY) === "android";
  } catch {
    return new URLSearchParams(window.location.search).get("source") === "android";
  }
}
