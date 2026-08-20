export type HandoffForm = Record<
  string,
  { description: string; phoneNumber: string }
>;

export type AgentForm = {
  displayName: string;
  greeting: string;
  profile: string;
  address: string;
  website: string;
  emails: string;
  phones: string;
  handoff: HandoffForm;
};
