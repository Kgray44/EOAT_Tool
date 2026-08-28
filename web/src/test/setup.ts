import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { transferableAbortController } from "node:util";
import { afterEach } from "vitest";

afterEach(cleanup);

// React Router creates native Request instances during in-memory navigations.
// Node 24 rejects jsdom's AbortSignal there, so keep the test environment on
// Node's matching AbortController implementation.
const nativeController = transferableAbortController();
Object.assign(globalThis, {
  AbortController: nativeController.constructor,
  AbortSignal: nativeController.signal.constructor,
});
