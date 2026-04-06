import type { LucideIcon } from 'lucide-react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import './ToolCard.css';

interface ToolCardProps {
  icon: LucideIcon;
  title: string;
  description: string;
  href?: string;
  comingSoon?: boolean;
  featured?: boolean;
}

export default function ToolCard({
  icon: Icon,
  title,
  description,
  href,
  comingSoon = false,
  featured = false,
}: ToolCardProps) {
  const classes = [
    'tool-card',
    featured   ? 'tool-card--featured'    : '',
    comingSoon ? 'tool-card--coming-soon' : 'tool-card--active',
  ].filter(Boolean).join(' ');

  const inner = (
    <>
      <div className="tool-card-top">
        <div className="tool-card-icon-wrap">
          <Icon size={featured ? 22 : 20} aria-hidden="true" />
        </div>
        {comingSoon && (
          <span className="tool-card-badge">Coming soon</span>
        )}
      </div>

      <div className="tool-card-body">
        <h3 className="tool-card-title">{title}</h3>
        <p className="tool-card-description">{description}</p>
      </div>

      {!comingSoon && href && (
        <div className="tool-card-footer">
          <span className="tool-card-cta">
            Open
            <ArrowRight size={14} aria-hidden="true" />
          </span>
        </div>
      )}
    </>
  );

  if (!comingSoon && href) {
    return (
      <Link to={href} className={classes}>
        {inner}
      </Link>
    );
  }

  return (
    <div
      className={classes}
      aria-label={comingSoon ? `${title} — coming soon` : undefined}
    >
      {inner}
    </div>
  );
}
