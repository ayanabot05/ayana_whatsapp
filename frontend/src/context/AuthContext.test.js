import React from "react";
import { render, act, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "./AuthContext";
import { api } from "../lib/api";

jest.mock("../lib/api");

const TestComponent = () => {
  const { user, config, logout } = useAuth();
  return (
    <div>
      <span data-testid="user">{user === false ? "false" : user ? user.name : "null"}</span>
      <span data-testid="config">{config ? "loaded" : "null"}</span>
      <button data-testid="logout-btn" onClick={logout}>Logout</button>
    </div>
  );
};

describe("AuthContext", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.get.mockImplementation((url) => {
      if (url === "/auth/me") return Promise.resolve({ data: { name: "Test User" } });
      if (url === "/config") return Promise.resolve({ data: { plans: [] } });
      return Promise.reject(new Error("Not found"));
    });
    api.post.mockImplementation((url) => {
      if (url === "/auth/logout") return Promise.resolve({ data: {} });
      if (url === "/auth/refresh") return Promise.resolve({ data: { user: { name: "Test User" } } });
      return Promise.resolve({ data: {} });
    });
  });

  test("valid session fetches user from /auth/me", async () => {
    const { getByTestId } = render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );

    expect(getByTestId("user").textContent).toBe("null");

    await waitFor(() => {
      expect(getByTestId("user").textContent).toBe("Test User");
    });
    expect(api.get).toHaveBeenCalledWith("/auth/me");
  });

  test("expired session sets user to false after failing refresh", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/auth/me") return Promise.reject(new Error("Unauthorized"));
      return Promise.resolve({ data: {} });
    });
    api.post.mockImplementation((url) => {
      if (url === "/auth/refresh") return Promise.reject(new Error("Refresh failed"));
      return Promise.resolve({ data: {} });
    });

    const { getByTestId } = render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(getByTestId("user").textContent).toBe("false");
    });
  });

  test("logout calls /auth/logout and clears user", async () => {
    const { getByTestId } = render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(getByTestId("user").textContent).toBe("Test User");
    });

    act(() => {
      getByTestId("logout-btn").click();
    });

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/auth/logout");
      expect(getByTestId("user").textContent).toBe("false");
    });
  });
});
