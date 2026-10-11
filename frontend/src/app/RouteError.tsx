import { isRouteErrorResponse, Link, useRouteError } from "react-router";
import { Button, EmptyState } from "@/components/ui";

export function RouteError() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : error instanceof Error ? error.message : "Unknown error";
  return (
    <div className="flex min-h-dvh items-center justify-center p-6">
      <div className="panel max-w-lg">
        <EmptyState
          title="This page crashed"
          actions={
            <>
              <Button variant="primary" onClick={() => window.location.reload()}>
                Reload
              </Button>
              <Link to="/">
                <Button>Go to dashboard</Button>
              </Link>
            </>
          }
        >
          <p>Something unexpected happened while rendering. Your games and analysis are stored on the server and are not affected.</p>
          <p className="num mt-2 text-xs text-ink-400">{message}</p>
        </EmptyState>
      </div>
    </div>
  );
}
