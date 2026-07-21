import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}
interface State {
  hasError: boolean;
}

export class AppErrorBoundary extends Component<Props, State> {
  public state: State = { hasError: false };
  public static getDerivedStateFromError(): State {
    return { hasError: true };
  }
  public render() {
    if (this.state.hasError)
      return (
        <main className="state state--error" role="alert">
          <h1>EOAT Atlas could not render this page</h1>
          <p>
            Reload the page. If the problem continues, contact the EOAT Atlas
            support team.
          </p>
        </main>
      );
    return this.props.children;
  }
}
