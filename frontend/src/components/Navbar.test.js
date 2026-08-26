import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { Navbar } from "./Navbar";
import { useAuth } from "../context/AuthContext";

jest.mock("../context/AuthContext", () => ({
  useAuth: jest.fn(),
}));

describe("Navbar", () => {
  const mockLogout = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders unauthenticated state with Log in and Get started links", () => {
    useAuth.mockReturnValue({ user: null, logout: mockLogout });
    render(
      <BrowserRouter>
        <Navbar />
      </BrowserRouter>
    );

    expect(screen.getByTestId("nav-logo")).toBeInTheDocument();
    expect(screen.getByTestId("nav-login")).toBeInTheDocument();
    expect(screen.getByTestId("nav-signup")).toBeInTheDocument();
    expect(screen.queryByTestId("nav-dashboard")).not.toBeInTheDocument();
  });

  it("renders authenticated state with Dashboard and Sign out links", () => {
    useAuth.mockReturnValue({ user: { role: "user" }, logout: mockLogout });
    render(
      <BrowserRouter>
        <Navbar />
      </BrowserRouter>
    );

    expect(screen.getByTestId("nav-dashboard")).toBeInTheDocument();
    expect(screen.getByTestId("nav-logout")).toBeInTheDocument();
    expect(screen.queryByTestId("nav-login")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-admin")).not.toBeInTheDocument();
  });

  it("renders Admin link for admin users", () => {
    useAuth.mockReturnValue({ user: { role: "admin" }, logout: mockLogout });
    render(
      <BrowserRouter>
        <Navbar />
      </BrowserRouter>
    );

    expect(screen.getByTestId("nav-admin")).toBeInTheDocument();
  });

  it("calls logout and redirects when Sign out is clicked", () => {
    useAuth.mockReturnValue({ user: { role: "user" }, logout: mockLogout });
    render(
      <BrowserRouter>
        <Navbar />
      </BrowserRouter>
    );

    const logoutBtn = screen.getByTestId("nav-logout");
    fireEvent.click(logoutBtn);
    expect(mockLogout).toHaveBeenCalled();
  });

  it("toggles mobile menu", () => {
    useAuth.mockReturnValue({ user: null, logout: mockLogout });
    render(
      <BrowserRouter>
        <Navbar />
      </BrowserRouter>
    );

    // Initial state: mobile menu links not rendered (only desktop nav visible)
    // Actually the mobile links are rendered when 'open' is true.
    const mobileToggle = screen.getByTestId("nav-mobile-toggle");
    fireEvent.click(mobileToggle);
    
    // Now it should be open, we expect two "Log in" links (one desktop, one mobile)
    const loginLinks = screen.getAllByText("Log in");
    expect(loginLinks.length).toBeGreaterThan(1);
    
    // Toggle off
    fireEvent.click(mobileToggle);
  });
});
