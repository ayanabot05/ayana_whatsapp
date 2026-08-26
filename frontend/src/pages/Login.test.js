import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Login from "./Login";
import { api } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { MemoryRouter, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

jest.mock("../lib/api");
jest.mock("../context/AuthContext");
jest.mock("react-router-dom", () => ({
  ...jest.requireActual("react-router-dom"),
  useNavigate: jest.fn(),
  useSearchParams: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

describe("Login Component", () => {
  const mockNavigate = jest.fn();
  const mockLoginWithToken = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    useNavigate.mockReturnValue(mockNavigate);
    useSearchParams.mockReturnValue([new URLSearchParams()]);
    useAuth.mockReturnValue({ loginWithToken: mockLoginWithToken });
  });

  test("renders login form fields", () => {
    render(<MemoryRouter><Login /></MemoryRouter>);
    expect(screen.getByTestId("login-email")).toBeInTheDocument();
    expect(screen.getByTestId("login-password")).toBeInTheDocument();
    expect(screen.getByTestId("login-submit")).toBeInTheDocument();
  });

  test("submits form and redirects to dashboard if onboarding complete", async () => {
    const mockUser = { name: "Test User", onboarding_complete: true };
    api.post.mockResolvedValueOnce({
      data: { access_token: "access", refresh_token: "refresh", user: mockUser },
    });

    render(<MemoryRouter><Login /></MemoryRouter>);
    
    await userEvent.type(screen.getByTestId("login-email"), "test@example.com");
    await userEvent.type(screen.getByTestId("login-password"), "password123");
    await userEvent.click(screen.getByTestId("login-submit"));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/auth/login", {
        email: "test@example.com",
        password: "password123",
      });
      expect(mockLoginWithToken).toHaveBeenCalledWith("access", "refresh", mockUser);
      expect(toast.success).toHaveBeenCalledWith("Welcome back, Test");
      expect(mockNavigate).toHaveBeenCalledWith("/dashboard");
    });
  });

  test("redirects to onboarding if not complete", async () => {
    const mockUser = { name: "Test User", onboarding_complete: false };
    api.post.mockResolvedValueOnce({
      data: { access_token: "access", refresh_token: "refresh", user: mockUser },
    });

    render(<MemoryRouter><Login /></MemoryRouter>);
    
    await userEvent.type(screen.getByTestId("login-email"), "test@example.com");
    await userEvent.type(screen.getByTestId("login-password"), "password123");
    await userEvent.click(screen.getByTestId("login-submit"));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/onboarding");
    });
  });

  test("displays error on failed login", async () => {
    api.post.mockRejectedValueOnce({
      response: { data: { detail: "Invalid credentials" } },
    });

    render(<MemoryRouter><Login /></MemoryRouter>);
    
    await userEvent.type(screen.getByTestId("login-email"), "test@example.com");
    await userEvent.type(screen.getByTestId("login-password"), "wrongpass");
    await userEvent.click(screen.getByTestId("login-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("login-error")).toHaveTextContent("Invalid credentials");
    });
  });
});
