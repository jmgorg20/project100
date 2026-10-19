// A random id for this browser, sent at sign-up so a free trial is given once per device. It is not
// a fingerprint: it is only this random value (kept in this browser), and the service stores a hash.
const KEY = "autoedit.device";

export function deviceId(): string {
  try {
    let id = localStorage.getItem(KEY);
    if (!id) {
      id = `dv-${crypto.randomUUID()}`;
      localStorage.setItem(KEY, id);
    }
    return id;
  } catch {
    return "";
  }
}
