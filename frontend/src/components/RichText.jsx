// Small renderer for the markdown the model writes: headings, lists, tables, **bold**, `code` and
// [citations]. It builds React elements only (no innerHTML), so answer text can never inject markup.

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\[[^\]]+\])/g;

function inline(text) {
  return text.split(INLINE).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    if (/^\[[^\]]+\]\(/.test(part)) return part.slice(1, part.indexOf("]")); // markdown link: text only, never a live URL
    if (part.startsWith("[") && part.endsWith("]")) return <span key={i} className="cite">{part.slice(1, -1)}</span>;
    return part;
  });
}

const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

export default function RichText({ text }) {
  const lines = text.split("\n");
  const blocks = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith("|") && /^\s*\|?[\s:-]+\|/.test(lines[i + 1] || "")) {
      const head = cells(line);
      const rows = [];
      for (i += 2; i < lines.length && lines[i].trim().startsWith("|"); i++) rows.push(cells(lines[i]));
      i--;
      blocks.push(
        <table key={blocks.length} className="md-table">
          <thead><tr>{head.map((h, j) => <th key={j}>{inline(h)}</th>)}</tr></thead>
          <tbody>{rows.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>)}</tbody>
        </table>,
      );
    } else if (/^\s*([-*•]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      for (; i < lines.length && /^\s*([-*•]|\d+\.)\s+/.test(lines[i]); i++) {
        items.push(<li key={items.length}>{inline(lines[i].replace(/^\s*([-*•]|\d+\.)\s+/, ""))}</li>);
      }
      i--;
      blocks.push(ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    } else if (/^#{1,6}\s/.test(line)) {
      blocks.push(<h4 key={blocks.length}>{inline(line.replace(/^#+\s/, ""))}</h4>);
    } else if (line.trim() && !/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      blocks.push(<p key={blocks.length}>{inline(line)}</p>);
    }
  }
  return <div className="answer">{blocks}</div>;
}
