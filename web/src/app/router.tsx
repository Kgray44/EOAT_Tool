import { createBrowserRouter, createMemoryRouter } from "react-router-dom";
import { App } from "@/app/App";
import { FoundationPage } from "@/pages/FoundationPage";
import { EoatProfilePage } from "@/pages/EoatProfilePage";
import { FitCheckPage } from "@/pages/FitCheckPage";
import { LibraryPage } from "@/pages/LibraryPage";
import { MachineProfilePage } from "@/pages/MachineProfilePage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { SearchPage } from "@/pages/SearchPage";
import { ToolProfilePage } from "@/pages/ToolProfilePage";

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
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routeDefinitions);

export function createTestRouter(initialEntries: string[]) {
  return createMemoryRouter(routeDefinitions, { initialEntries });
}
