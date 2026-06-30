// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockUseAuth = vi.fn();

vi.mock("../auth", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("../useTheme", () => ({
  useTheme: () => ({ theme: "light", toggle: vi.fn() }),
}));

vi.mock("../api", () => ({
  createPad: vi.fn(),
}));

import Landing from "./Landing";

describe("Landing", () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
  });

  it("shows a sign-in action for signed-out visitors and a dashboard link for signed-in users", () => {
    mockUseAuth.mockReturnValue({
      user: null,
      ready: true,
      login: vi.fn(),
      signup: vi.fn(),
      logout: vi.fn(),
      authedFetch: vi.fn(),
      getAccessToken: vi.fn(),
      reloadUser: vi.fn(),
    });

    const { rerender } = render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>
    );
    expect(screen.getByRole("link", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /my pads/i })).not.toBeInTheDocument();

    mockUseAuth.mockReturnValue({
      user: {
        id: "u1",
        username: "demo",
        email: "demo@example.com",
        display_name: "Demo",
        email_verified: true,
        created_at: "2024-01-01T00:00:00.000Z",
      },
      ready: true,
      login: vi.fn(),
      signup: vi.fn(),
      logout: vi.fn(),
      authedFetch: vi.fn(),
      getAccessToken: vi.fn(),
      reloadUser: vi.fn(),
    });

    rerender(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>
    );
    expect(screen.getByRole("link", { name: /my pads/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /sign in/i })).not.toBeInTheDocument();
  });
});
