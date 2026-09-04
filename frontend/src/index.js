// Sentry MUST be the first import so it can catch startup errors too.
import "./instrument";

import React from "react";
import ReactDOM from "react-dom/client";
import * as Sentry from "@sentry/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/index.css";
import App from "@/App";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

// React 19 root-level error hooks: report even when no boundary catches.
const root = ReactDOM.createRoot(document.getElementById("root"), {
  onUncaughtError: Sentry.reactErrorHandler(),
  onCaughtError: Sentry.reactErrorHandler(),
  onRecoverableError: Sentry.reactErrorHandler(),
});

root.render(
  <React.StrictMode>
    <Sentry.ErrorBoundary
      fallback={
        <main role="alert" className="min-h-screen flex items-center justify-center px-6 bg-ayana-bg text-ayana-text">
          <div className="max-w-md text-center space-y-4">
            <h1 className="text-2xl font-serif">We hit a snag.</h1>
            <p className="text-ayana-secondary">
              Please refresh the page. If this keeps happening, WhatsApp us —
              we'll fix it fast.
            </p>
            <button
              onClick={() => window.location.reload()}
              className="px-6 py-3 rounded-full bg-ayana-primary text-white font-semibold hover:bg-ayana-primary-hover"
              data-testid="error-boundary-reload"
            >
              Refresh page
            </button>
          </div>
        </main>
      }
    >
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </Sentry.ErrorBoundary>
  </React.StrictMode>,
);
