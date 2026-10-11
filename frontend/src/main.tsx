import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { Layout } from "@/app/Layout";
import { RouteError } from "@/app/RouteError";
import { Spinner } from "@/components/ui";
import { ApiError, errorMessage } from "@/lib/api";
import { toast } from "@/stores/toast";
import "@/styles/index.css";

const Dashboard = lazy(() => import("@/features/dashboard/DashboardPage"));
const Play = lazy(() => import("@/features/play/PlayPage"));
const Analysis = lazy(() => import("@/features/analysis/AnalysisPage"));
const Games = lazy(() => import("@/features/games/GamesPage"));
const Review = lazy(() => import("@/features/review/ReviewPage"));
const Import = lazy(() => import("@/features/imports/ImportPage"));
const Explorer = lazy(() => import("@/features/explorer/ExplorerPage"));
const EngineLab = lazy(() => import("@/features/engine-lab/EngineLabPage"));
const SettingsPage = lazy(() => import("@/features/settings/SettingsPage"));
const NotFound = lazy(() => import("@/app/NotFound"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      // Do not hammer the server on client errors; retry transient failures once.
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 1,
    },
  },
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      if (!mutation.options.onError) toast.error("Action failed", errorMessage(error));
    },
  }),
});

function page(element: React.ReactNode) {
  return (
    <Suspense
      fallback={
        <div className="flex h-64 items-center justify-center">
          <Spinner className="size-6" />
        </div>
      }
    >
      {element}
    </Suspense>
  );
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    errorElement: <RouteError />,
    children: [
      { path: "/", element: page(<Dashboard />) },
      { path: "/play", element: page(<Play />) },
      { path: "/analysis", element: page(<Analysis />) },
      { path: "/games", element: page(<Games />) },
      { path: "/games/:gameId", element: page(<Review />) },
      { path: "/import", element: page(<Import />) },
      { path: "/explorer", element: page(<Explorer />) },
      { path: "/lab", element: page(<EngineLab />) },
      { path: "/settings", element: page(<SettingsPage />) },
      { path: "*", element: page(<NotFound />) },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
