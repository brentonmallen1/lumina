import type { LucideIcon } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
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
  const navigate = useNavigate();

  const handleClick = () => {
    if (!comingSoon && href) navigate(href);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.key === 'Enter' || e.key === ' ') && !comingSoon && href) {
      e.preventDefault();
      navigate(href);
    }
  };

  return (
    <div
      className={[
        'tool-card',
        featured   ? 'tool-card--featured'     : '',
        comingSoon ? 'tool-card--coming-soon'  : 'tool-card--active',
      ].join(' ').trim()}
      role={!comingSoon && href ? 'button' : undefined}
      tabIndex={!comingSoon && href ? 0 : undefined}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      aria-label={comingSoon ? `${title} — coming soon` : title}
    >
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
    </div>
  );
}
