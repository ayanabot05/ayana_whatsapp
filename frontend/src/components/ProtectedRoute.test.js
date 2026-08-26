import React from "react";
import { render, screen } from "@testing-library/react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ProtectedRoute } from "./ProtectedRoute";
import { useAuth } from "../context/AuthContext";

// Mock Navigate from react-router-dom to just render a text indicating redirection
jest.mock("react-router-dom", () => {
  const originalModule = jest.requireActual("react-router-dom");
  return {
    ...originalModule,
    Navigate: ({ to }) => <div data-testid="navigate">Redirected to {to}</div>,
  };
});

jest.mock("../context/AuthContext", () => ({
  useAuth: jest.fn(),
}));

describe("ProtectedRoute", () => {
  it("renders loader when user is null", () => {
    useAuth.mockReturnValue({ user: null });
    const { container } = render(
      <BrowserRouter>
        <ProtectedRoute>
          <div data-testid="child">Protected Content</div>
        </ProtectedRoute>
      </BrowserRouter>
    );
    expect(screen.queryByTestId("child")).not.toBeInTheDocument();
    // A loader element has animate-spin class
    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
  });

  it("redirects to login when user is false (unauthenticated)", () => {
    useAuth.mockReturnValue({ user: false });
    render(
      <BrowserRouter>
        <ProtectedRoute>
          <div data-testid="child">Protected Content</div>
        </ProtectedRoute>
      </BrowserRouter>
    );
    expect(screen.getByTestId("navigate")).toHaveTextContent("Redirected to /login");
  });

  it("renders children when user is authenticated", () => {
    useAuth.mockReturnValue({ user: { role: "user" } });
    render(
      <BrowserRouter>
        <ProtectedRoute>
          <div data-testid="child">Protected Content</div>
        </ProtectedRoute>
      </BrowserRouter>
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });

  it("redirects to dashboard when adminOnly is true and user is not admin", () => {
    useAuth.mockReturnValue({ user: { role: "user" } });
    render(
      <BrowserRouter>
        <ProtectedRoute adminOnly>
          <div data-testid="child">Protected Content</div>
        </ProtectedRoute>
      </BrowserRouter>
    );
    expect(screen.getByTestId("navigate")).toHaveTextContent("Redirected to /dashboard");
  });

  it("renders children when adminOnly is true and user is admin", () => {
    useAuth.mockReturnValue({ user: { role: "admin" } });
    render(
      <BrowserRouter>
        <ProtectedRoute adminOnly>
          <div data-testid="child">Protected Content</div>
        </ProtectedRoute>
      </BrowserRouter>
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });
});
