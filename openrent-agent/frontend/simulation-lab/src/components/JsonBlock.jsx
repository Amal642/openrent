export default function JsonBlock({ value, empty = "No data." }) {
  if (value === undefined || value === null || value === "") {
    return <pre className="code-block muted">{empty}</pre>;
  }

  const content =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return <pre className="code-block">{content}</pre>;
}
