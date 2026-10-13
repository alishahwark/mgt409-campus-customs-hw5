import { RotateCcw, RefreshCw } from 'lucide-react';
import type { Page } from './Sidebar';

const titles: Record<Page, { title: string; subtitle: string }> = {
  overview: { title: 'Operations', subtitle: 'Campus Customs / Internal desk' },
  tickets: { title: 'Tickets', subtitle: 'Requests, decisions, and outcomes' },
  activity: { title: 'Agent Activity', subtitle: 'Recorded work and tool calls' },
  approvals: { title: 'Approvals', subtitle: 'Human decisions required' },
};

export function Header({ page, online, updatedAt, refreshing, onRefresh, onReset }: {
  page: Page; online: boolean; updatedAt: Date | null; refreshing: boolean;
  onRefresh: () => void; onReset: () => void;
}) {
  const { title, subtitle } = titles[page];
  return <header className="header">
    <div className="header__titles"><h1>{title}</h1><p>{subtitle}</p></div>
    <div className="header__actions">
      <span className="header__connection"><span className={`connection-dot${online ? ' connection-dot--online' : ''}`} aria-hidden="true" />{online ? 'Connected' : 'Disconnected'}</span>
      <span className="header__updated">{updatedAt ? `Updated ${updatedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'No refresh yet'}</span>
      <button className="icon-button" type="button" onClick={onRefresh} disabled={refreshing} aria-label="Refresh data" title="Refresh data"><RefreshCw size={17} className={refreshing ? 'spin' : ''} /></button>
      <button className="text-button" type="button" onClick={onReset}><RotateCcw size={15} /> Reset Shop</button>
    </div>
  </header>;
}
