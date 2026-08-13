import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { AppProviders } from "@/app/providers";
import { ReleaseParityGate } from "@/app/ReleaseParityGate";
import { createAppRouter } from "@/app/router";
import "@/styles/admin.css";
import "@/styles/tokens.css";
import "@/styles/global.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ReleaseParityGate>
      <AppProviders>
        <RouterProvider router={createAppRouter()} />
      </AppProviders>
    </ReleaseParityGate>
  </StrictMode>,
);
