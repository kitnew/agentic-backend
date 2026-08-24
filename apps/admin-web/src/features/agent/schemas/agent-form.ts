export type AgentHandoffDestinationForm = {
  id: string;
  key: string;
  description: string;
  phoneNumber: string;
};

export type AgentForm = {
  displayName: string;
  greeting: string;
  profile: string;
  defaultLocale: string;
  timezone: string;
  address: string;
  website: string;
  emails: string;
  phones: string;
  handoffDestinations: AgentHandoffDestinationForm[];
};
