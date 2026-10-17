// Status chips. The tone conveys the state category; the text always states it
// in words too, so the UI never relies on colour alone.
export default function StatusBadge({ tone = 'neutral', children }) {
  return <span className={`status-badge status-${tone}`}>{children}</span>;
}
