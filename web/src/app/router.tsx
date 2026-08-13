import { createBrowserRouter, createMemoryRouter } from "react-router-dom";

import { AdminApp } from "@/app/AdminApp";
import { App } from "@/app/App";
import { DesktopBoundaryPage } from "@/pages/DesktopBoundaryPage";
import { EoatProfilePage } from "@/pages/EoatProfilePage";
import { FitCheckPage } from "@/pages/FitCheckPage";
import { FoundationPage } from "@/pages/FoundationPage";
import { LibraryPage } from "@/pages/LibraryPage";
import { MachineProfilePage } from "@/pages/MachineProfilePage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { SearchPage } from "@/pages/SearchPage";
import { SetupPacketPage } from "@/pages/SetupPacketPage";
import { ToolProfilePage } from "@/pages/ToolProfilePage";

/**
 * The normal application and governed Admin are siblings in one router.
 * Admin retains its existing nested absolute routes; normal profiles remain
 * ordinary same-origin read routes and never inherit Admin UI or authority.
 */
export const routeDefinitions = [
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <FoundationPage /> },
      { path: "search", element: <SearchPage /> },
      { path: "library", element: <LibraryPage /> },
      { path: "eoats/:identifier", element: <EoatProfilePage /> },
      { path: "machines/:number", element: <MachineProfilePage /> },
      { path: "tools/:identifier", element: <ToolProfilePage /> },
      { path: "fit-check", element: <FitCheckPage /> },
      { path: "setup-packet", element: <SetupPacketPage /> },
      { path: "standards", element: <DesktopBoundaryPage kind="standards" /> },
      { path: "data-health", element: <DesktopBoundaryPage kind="data-health" /> },
    ],
  },
  { path: "/admin/*", element: <AdminApp /> },
  { path: "*", element: <NotFoundPage /> },
];

export function createAppRouter() {
  return createBrowserRouter(routeDefinitions);
}

export function createTestRouter(initialEntries: string[]) {
  return createMemoryRouter(routeDefinitions, { initialEntries });
}
