import { z } from "zod";

export const agentFormSchema = z.object({
  displayName: z.string().trim().min(1, "Agent name is required").max(100),
  greeting: z.string().trim().min(1, "Greeting is required").max(1000),
  profile: z.string().trim().min(1, "Profile is required").max(100),
  defaultLocale: z
    .string()
    .trim()
    .regex(/^[a-z]{2,3}(?:-[A-Z]{2})?$/, "Use a locale such as sk-SK"),
  tenantInstructions: z
    .string()
    .trim()
    .min(1, "Tenant instructions are required"),
  voiceId: z.string().trim().max(255),
});

export type AgentForm = z.infer<typeof agentFormSchema>;
