import { useMemo, useState } from 'react';

import { createClient } from './api/client.js';
import Shell from './components/Shell.jsx';
import { createMockRemediationStore } from './mock/remediationStore.js';
import AnomalyFeed from './views/AnomalyFeed.jsx';
import ForecastView from './views/ForecastView.jsx';
import PredictionAlerts from './views/PredictionAlerts.jsx';
import RcaRanking from './views/RcaRanking.jsx';
import RemediationQueue from './views/RemediationQueue.jsx';

export const VIEWS = [
  { id: 'anomalies', label: 'Anomaly feed' },
  { id: 'rca', label: 'RCA ranking' },
  { id: 'predictions', label: 'Prediction alerts' },
  { id: 'forecasts', label: 'Forecast' },
  { id: 'remediations', label: 'Remediation queue' },
];

function ConfigErrorPage({ message }) {
  return (
    <div className="config-error">
      <h1>AIOps dashboard — configuration error</h1>
      <p>{message}</p>
      <p>No data source was started. Fix the variable and reload; the default (unset) is mock mode.</p>
    </div>
  );
}

// `initialMode` sets the starting mode (from VITE_API_MODE in main.jsx and
// default 'mock'); the header toggle switches it at runtime. The mode decides
// the only client used for reads, and the remediation queue branches on it, so
// switching modes cannot carry a mock action into live mode.
export default function App({ initialMode = 'mock', configError = null, fetchImpl }) {
  const [mode, setMode] = useState(initialMode);
  const [viewId, setViewId] = useState(VIEWS[0].id);
  const [mockStore] = useState(() => createMockRemediationStore());
  const client = useMemo(() => createClient(mode, { fetchImpl }), [mode, fetchImpl]);

  if (configError) return <ConfigErrorPage message={configError} />;

  return (
    <Shell
      mode={mode}
      onModeChange={setMode}
      views={VIEWS}
      activeViewId={viewId}
      onNavigate={setViewId}
    >
      {viewId === 'anomalies' && <AnomalyFeed read={client.read} />}
      {viewId === 'rca' && <RcaRanking read={client.read} />}
      {viewId === 'predictions' && <PredictionAlerts read={client.read} />}
      {viewId === 'forecasts' && <ForecastView read={client.read} />}
      {viewId === 'remediations' && (
        <RemediationQueue mode={mode} read={client.read} store={mockStore} />
      )}
    </Shell>
  );
}
