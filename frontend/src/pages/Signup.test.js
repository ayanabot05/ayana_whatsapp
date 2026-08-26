import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Signup from "./Signup";
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

// Mock PhoneInput component
jest.mock("../components/PhoneInput", () => ({
  PhoneInput: ({ value, onChange, testid }) => (
    <input
      data-testid={testid}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));

describe("Signup Component", () => {
  const mockNavigate = jest.fn();
  const mockLoginWithToken = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    useNavigate.mockReturnValue(mockNavigate);
    useSearchParams.mockReturnValue([new URLSearchParams()]);
    useAuth.mockReturnValue({ loginWithToken: mockLoginWithToken });
  });

  test("renders signup form fields", () => {
    render(<MemoryRouter><Signup /></MemoryRouter>);
    expect(screen.getByTestId("signup-name")).toBeInTheDocument();
    expect(screen.getByTestId("signup-email")).toBeInTheDocument();
    expect(screen.getByTestId("signup-phone")).toBeInTheDocument();
    expect(screen.getByTestId("signup-password")).toBeInTheDocument();
  });

  test("submits form and redirects to onboarding", async () => {
    const mockUser = { name: "Test User", household_owner_id: null };
    api.post.mockResolvedValueOnce({
      data: { access_token: "access", refresh_token: "refresh", user: mockUser },
    });

    render(<MemoryRouter><Signup /></MemoryRouter>);
    
    await userEvent.type(screen.getByTestId("signup-name"), "Test User");
    await userEvent.type(screen.getByTestId("signup-email"), "test@example.com");
    await userEvent.type(screen.getByTestId("signup-password"), "password123");
    // phone is pre-filled with "+91", we can append
    await userEvent.type(screen.getByTestId("signup-phone"), "9876543210");
    
    await userEvent.click(screen.getByTestId("signup-submit"));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/auth/register", {
        name: "Test User",
        email: "test@example.com",
        phone: "+919876543210",
        password: "password123",
      });
      expect(mockLoginWithToken).toHaveBeenCalledWith("access", "refresh", mockUser);
      expect(toast.success).toHaveBeenCalledWith("Account created. Let's set up their care circle.");
      expect(mockNavigate).toHaveBeenCalledWith("/onboarding");
    });
  });

  test("redirects to dashboard if user has household_owner_id (auto-joined invite)", async () => {
    const mockUser = { name: "Test User", household_owner_id: "123" };
    api.post.mockResolvedValueOnce({
      data: { access_token: "access", refresh_token: "refresh", user: mockUser },
    });

    render(<MemoryRouter><Signup /></MemoryRouter>);
    
    await userEvent.type(screen.getByTestId("signup-name"), "Test User");
    await userEvent.type(screen.getByTestId("signup-password"), "password123");
    await userEvent.click(screen.getByTestId("signup-submit"));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/dashboard");
    });
  });

  test("displays validation errors", async () => {
    api.post.mockRejectedValueOnce({
      response: { data: { detail: "Email already registered" } },
    });

    render(<MemoryRouter><Signup /></MemoryRouter>);
    
    await userEvent.type(screen.getByTestId("signup-name"), "Test User");
    await userEvent.type(screen.getByTestId("signup-password"), "password123");
    await userEvent.click(screen.getByTestId("signup-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("signup-error")).toHaveTextContent("Email already registered");
    });
  });
});
