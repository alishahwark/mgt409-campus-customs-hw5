import type { ReactNode } from 'react';

export type DisplayStatus = 'open' | 'running' | 'awaiting' | 'resolved' | 'blocked' | 'idle' | 'completed' | 'waiting';

const labels: Record<DisplayStatus, string> = {
  open: 'Open', running: 'Running', awaiting: 'Awaiting approval', resolved: 'Resolved',
  blocked: 'Blocked', idle: 'Idle', completed: 'Completed', waiting: 'Waiting',
};

export function Status({ value, children }: { value: DisplayStatus; children?: ReactNode }) {
  return <span className={`status status--${value}`}><span className="status__dot" aria-hidden="true" />{children ?? labels[value]}</span>;
}
