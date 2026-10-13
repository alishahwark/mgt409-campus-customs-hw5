export function MetricsStrip({ open, active, approvals, resolved }: { open: number; active: number; approvals: number; resolved: number }) {
  const metrics = [
    { label: 'Open tickets', value: open, note: 'Needs attention' },
    { label: 'Active runs', value: active, note: 'This browser session' },
    { label: 'Pending approvals', value: approvals, note: 'From team runs here' },
    { label: 'Resolved', value: resolved, note: 'Database confirmed' },
  ];
  return <section className="metrics" aria-label="Operations metrics">{metrics.map(metric =>
    <div className="metric" key={metric.label}><span className="eyebrow">{metric.label}</span><strong>{metric.value}</strong><span className="metric__note">{metric.note}</span></div>
  )}</section>;
}
