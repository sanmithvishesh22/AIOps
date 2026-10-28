// Deep copy for the mock data source and the mock remediation store, so a view
// can never mutate the fixtures or the store's rows by accident. JSON-based on
// purpose: the data involved is JSON by contract (the read-API answers JSON
// arrays), and this keeps the UI free of cloning dependencies.
export function deepCopy(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}
