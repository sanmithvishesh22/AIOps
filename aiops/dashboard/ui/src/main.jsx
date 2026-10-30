import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from './App.jsx';
import { modeConfigErrorMessage, parseApiMode } from './api/mode.js';
import './styles.css';

// The mode is configured explicitly at build/dev time (ticket D4-003 §4):
//   VITE_API_MODE=live  → live read-only mode
//   unset, or =mock     → mock mode (the default for a new local install)
// An unrecognised value renders a configuration error instead of quietly
// showing synthetic data as if it were live.
const parsed = parseApiMode(import.meta.env.VITE_API_MODE);
const configError = parsed === 'invalid' ? modeConfigErrorMessage(import.meta.env.VITE_API_MODE) : null;

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App initialMode={parsed === 'invalid' ? 'mock' : parsed} configError={configError} />
  </StrictMode>,
);
