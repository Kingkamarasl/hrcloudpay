import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Navbar from './Navbar';
import Sidebar from './Sidebar';
import CommandPalette from './CommandPalette';
import AIChatWidget from './AIChatWidget';

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const { pathname } = useLocation();

  // The floating widget and the dedicated /ai page are two separate components with
  // their own conversation state, both POSTing to the same endpoint. Mounting both
  // at once left two live, divergent copies of the same conversation. The full page
  // supersedes the widget, so suppress the widget on that route.
  const widgetHidden = pathname === '/ai';

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth > 900) setSidebarOpen(false);
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return (
    <div className={`app-shell ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <div
        className="sidebar-backdrop"
        onClick={() => setSidebarOpen(false)}
        aria-hidden={!sidebarOpen}
      />
      <Sidebar onNavigate={() => setSidebarOpen(false)} />
      <div className="app-main">
        <Navbar
          onMenuClick={() => setSidebarOpen((v) => !v)}
          onSearchClick={() => setPaletteOpen(true)}
        />
        <main className="app-content">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      {!widgetHidden && <AIChatWidget />}
    </div>
  );
}