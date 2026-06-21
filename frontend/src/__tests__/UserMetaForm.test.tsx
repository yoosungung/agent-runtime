import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { UserMetaForm } from "../components/UserMetaForm";

describe("UserMetaForm", () => {
  it("renders template fields", () => {
    render(
      <UserMetaForm
        template={{
          description: "Connect mailbox",
          fields: [
            {
              path: "outlook.mailbox",
              label: "Mailbox",
              required: true,
            },
          ],
        }}
        value={{}}
        onChange={vi.fn()}
        secretsRef=""
        onSecretsRefChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Connect mailbox")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("outlook.mailbox")).toBeInTheDocument();
  });
});
