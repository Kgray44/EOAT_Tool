import { createBrowserRouter, createMemoryRouter } from "react-router-dom";
import { App } from "@/app/App";
import { FoundationPage } from "@/pages/FoundationPage";
import { EoatProfilePage } from "@/pages/EoatProfilePage";
import { FutureRoutePage } from "@/pages/FutureRoutePage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export const routeDefinitions = [
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <FoundationPage /> },
      { path: "search", element: <FutureRoutePage title="Search" /> },
      { path: "library", element: <FutureRoutePage title="Library" /> },
      { path: "eoats/:identifier", element: <EoatProfilePage /> },
      {
        path: "machines/:number",
        element: <FutureRoutePage title="Machine profile" />,
      },
      {
        path: "tools/:identifier",
        element: <FutureRoutePage title="Tool profile" />,
      },
      { path: "fit-check", element: <FutureRoutePage title="Fit Check" /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routeDefinitions);

export function createTestRouter(initialEntries: string[]) {
  return createMemoryRouter(routeDefinitions, { initialEntries });
}
