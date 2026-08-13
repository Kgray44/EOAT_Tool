import "@testing-library/jest-dom/vitest";
import { transferableAbortController } from "node:util";

// React Router creates native Request instances during in-memory navigations.
// Node 24 rejects jsdom's AbortSignal there, so keep the test environment on
// Node's matching AbortController implementation.
const nativeController = transferableAbortController();
Object.assign(globalThis, {
  AbortController: nativeController.constructor,
  AbortSignal: nativeController.signal.constructor,
});
