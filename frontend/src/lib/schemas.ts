import { z } from "zod";

export const nameSchema = z
  .string()
  .regex(/^[a-z0-9][a-z0-9-]{0,127}$/, "lowercase letters, numbers, hyphens");
export const versionSchema = z.string().regex(/^[a-zA-Z0-9._-]{1,64}$/);
export const entrypointSchema = z.string().regex(/^[\w.]+:[\w]+$/);
export const checksumSchema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
export const secretsRefSchema = z.string().regex(/^(vault|env|aws-sm):\/\/.+$/);
export const usernameSchema = z.string().regex(/^[a-zA-Z0-9_.-]{3,128}$/);
export const principalIdSchema = z.string().regex(/^[\w.:@-]{1,128}$/);

export const sourceMetaCreateSchema = z.object({
  kind: z.enum(["agent", "mcp"]),
  name: nameSchema,
  version: versionSchema,
  runtime_pool: z.string().min(1),
  entrypoint: entrypointSchema,
  bundle_uri: z.string().optional(),
  checksum: checksumSchema.optional(),
  config: z.record(z.string(), z.unknown()).optional(),
});

export const userCreateSchema = z.object({
  username: usernameSchema,
  password: z.string().min(12, "Minimum 12 characters"),
  tenant: z.string().optional(),
  is_admin: z.boolean(),
});

export const passwordSchema = z.string().min(12, "Minimum 12 characters");
