// A successful read with no rows: a real answer, clearly not an error.
export default function EmptyState({ title, detail }) {
  return (
    <div className="state-block state-empty">
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}
