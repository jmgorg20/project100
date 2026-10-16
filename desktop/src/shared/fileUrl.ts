// A file:// URL for a local path (Windows or POSIX), safe for names with spaces, #, ?, %.
export function fileUrl(filePath: string): string {
  let p = filePath.replace(/\\/g, "/");
  if (/^[A-Za-z]:\//.test(p)) p = `/${p}`; // C:/x -> /C:/x
  else if (p.startsWith("//")) return `file:${p.split("/").map(encodeURIComponent).join("/")}`; // UNC
  const encoded = p
    .split("/")
    .map((part, i) => (i === 1 && /^[A-Za-z]:$/.test(part) ? part : encodeURIComponent(part)))
    .join("/");
  return `file://${encoded}`;
}
