import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";
import { App } from "./app/App";
import { ApiError } from "./lib/api";
import { AuthProvider } from "./lib/auth";
import { ThemeProvider } from "./lib/theme";
import "./styles/index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 20_000,
      refetchOnWindowFocus: false,
      retry: (n, e) => !(e instanceof ApiError && [401, 403, 404, 422].includes(e.status)) && n < 1,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <TooltipPrimitive.Provider>
            <BrowserRouter>
              <App />
            </BrowserRouter>
            <Toaster theme="system" position="bottom-right" richColors closeButton toastOptions={{ className: "!font-sans" }} />
          </TooltipPrimitive.Provider>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
