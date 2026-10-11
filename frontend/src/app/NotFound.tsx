import { Link } from "react-router";
import { Button, EmptyState, Panel } from "@/components/ui";

export default function NotFound() {
  return (
    <Panel>
      <EmptyState
        title="Page not found"
        actions={
          <Link to="/">
            <Button variant="primary">Back to dashboard</Button>
          </Link>
        }
      >
        That address does not match any page in ChessLab.
      </EmptyState>
    </Panel>
  );
}
