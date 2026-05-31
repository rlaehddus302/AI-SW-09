import { useEffect, useState } from 'react';
import DashboardPage from './pages/DashboardPage';
import SetupPage from './pages/SetupPage';
import { storeIdStorage } from './services/api';

function currentPath() {
  return window.location.pathname === '/' ? '/' : window.location.pathname;
}

export default function App() {
  const [path, setPath] = useState(currentPath);

  const navigate = (nextPath, options = {}) => {
    const method = options.replace ? 'replaceState' : 'pushState';
    window.history[method]({}, '', nextPath);
    setPath(nextPath);
  };

  useEffect(() => {
    const onPopState = () => setPath(currentPath());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    const storeId = storeIdStorage.get();
    if (path === '/') {
      navigate(storeId ? '/dashboard' : '/setup', { replace: true });
      return;
    }

    if (path === '/dashboard' && !storeId) {
      navigate('/setup', { replace: true });
    }
  }, [path]);

  if (path === '/setup') {
    return <SetupPage onComplete={() => navigate('/dashboard')} />;
  }

  if (path === '/dashboard') {
    return <DashboardPage onSetup={() => navigate('/setup')} />;
  }

  return (
    <main className="not-found">
      <h1>페이지를 찾을 수 없습니다</h1>
      <button type="button" className="button button--primary" onClick={() => navigate('/')}>
        처음으로
      </button>
    </main>
  );
}
