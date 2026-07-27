import { createBrowserRouter, createMemoryRouter } from "react-router-dom";
import { App } from "@/app/App";
import { FoundationPage } from "@/pages/FoundationPage";
import { EoatProfilePage } from "@/pages/EoatProfilePage";
import { FitCheckPage } from "@/pages/FitCheckPage";
import { LibraryPage } from "@/pages/LibraryPage";
import { MachineProfilePage } from "@/pages/MachineProfilePage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { SearchPage } from "@/pages/SearchPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { ToolProfilePage } from "@/pages/ToolProfilePage";
import { DesktopBoundaryPage } from "@/pages/DesktopBoundaryPage";

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
      {
        path: "setup-packet",
        element: <DesktopBoundaryPage kind="setup-packet" />,
      },
      { path: "standards", element: <DesktopBoundaryPage kind="standards" /> },
      {
        path: "data-health",
        element: <DesktopBoundaryPage kind="data-health" />,
      },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routeDefinitions);
}

export function createTestRouter(initialEntries: string[]) {
  return createMemoryRouter(routeDefinitions, { initialEntries });
}
