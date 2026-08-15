import { EmptyState, PageHeader } from "../../components/page-states";

export function OverviewPage() {
  return (
    <>
      <PageHeader
        title="Overview"
        detail="Platform foundation is ready for feature modules."
      />
      <EmptyState
        title="No platform status yet"
        detail="Future global modules can add their own routes and metadata."
      />
    </>
  );
}
