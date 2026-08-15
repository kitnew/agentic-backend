import { AppRouter } from "../routes/router";
import { AppProviders } from "./providers";

export function App() {
  return (
    <AppProviders>
      <AppRouter />
    </AppProviders>
  );
}
