// Vitest setup: jest-dom matchers (toBeDisabled, toHaveTextContent, ...).
// Deliberately at the ui/ root, not under test/: the Express package's
// `node --test` discovery would run any plain .js file under **/test/**.
import '@testing-library/jest-dom/vitest';
