import { Link, Outlet, useLocation } from 'react-router-dom';
import { Settings, Zap, Sun, Moon } from 'lucide-react';
import { useTheme } from '../hooks/useTheme';
import './Layout.css';

export default function Layout() {
  const location = useLocation();
  const isSettings = location.pathname === '/settings';
  const { isDark, toggle } = useTheme();

  return (
    <div className="layout">
      <header className="layout-header">
        <Link to="/" className="layout-brand">
          <Zap size={20} className="layout-brand-icon" aria-hidden="true" />
          <span className="layout-brand-name">Distill</span>
        </Link>

        <nav className="layout-nav" aria-label="Global navigation">
          <button
            className="layout-nav-btn"
            onClick={toggle}
            aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            title={isDark ? 'Light mode' : 'Dark mode'}
          >
            {isDark ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <Link
            to="/settings"
            className={`layout-nav-btn ${isSettings ? 'active' : ''}`}
            aria-label="Settings"
            title="Settings"
          >
            <Settings size={18} />
          </Link>
        </nav>
      </header>

      <main className="layout-main">
        <Outlet />
      </main>
    </div>
  );
}
