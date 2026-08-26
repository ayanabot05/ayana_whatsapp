import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import InviteClaim from "./InviteClaim";
import { api } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { MemoryRouter, Routes, Route, useNavigate } from "react-router-dom";
import { toast } from "sonner";

jest.mock("../lib/api");
jest.mock("../context/AuthContext");
jest.mock("react-router-dom", () => ({
  ...jest.requireActual("react-router-dom"),
  useNavigate: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

describe("InviteClaim Component", () => {
  const mockNavigate = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    useNavigate.mockReturnValue(mockNavigate);
  });

  const renderComponent = (token = "test-token") => {
    return render(
      <MemoryRouter initialEntries={[`/invite/${token}`]}>
        <Routes>
          <Route path="/invite/:token" element={<InviteClaim />} />
        </Routes>
      </MemoryRouter>
    );
  };

  test("shows loading state initially", () => {
    useAuth.mockReturnValue({ user: null });
    api.get.mockImplementation(() => new Promise(() => {})); // Never resolves to keep loading
    
    renderComponent();
    expect(screen.getByRole("status") || document.querySelector(".animate-spin")).toBeInTheDocument();
  });

  test("shows error if token is expired (410)", async () => {
    useAuth.mockReturnValue({ user: null });
    api.get.mockRejectedValue({ response: { status: 410, data: { detail: "Invite expired" } } });
    
    renderComponent();
    
    await waitFor(() => {
      expect(screen.getByText("This invite has expired")).toBeInTheDocument();
    });
  });

  test("auto-accepts if user is logged in with matching email", async () => {
    useAuth.mockReturnValue({ user: { email: "test@example.com" } });
    api.get.mockResolvedValue({ data: { email: "test@example.com", inviter_name: "Inviter" } });
    api.post.mockResolvedValue({ data: {} });
    
    renderComponent();
    
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/circle/invite/test-token/accept");
      expect(screen.getByText("Welcome to the care circle! 💛")).toBeInTheDocument();
    });
  });

  test("shows mismatched email warning if logged in with wrong email", async () => {
    useAuth.mockReturnValue({ user: { email: "wrong@example.com" } });
    api.get.mockResolvedValue({ data: { email: "test@example.com", inviter_name: "Inviter" } });
    
    renderComponent();
    
    await waitFor(() => {
      expect(screen.getByText("Wrong account")).toBeInTheDocument();
      expect(screen.getByText(/Please log out and sign in with the invited email address/i)).toBeInTheDocument();
    });
  });

  test("shows unauth CTAs if not logged in", async () => {
    useAuth.mockReturnValue({ user: null });
    api.get.mockResolvedValue({ data: { email: "test@example.com", inviter_name: "Inviter" } });
    
    renderComponent();
    
    await waitFor(() => {
      expect(screen.getByText(/Create account & accept/i)).toBeInTheDocument();
      expect(screen.getByText(/Already have an account\? Log in/i)).toBeInTheDocument();
    });
  });
});
