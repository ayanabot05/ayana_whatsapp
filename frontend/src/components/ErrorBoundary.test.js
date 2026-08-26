import React from "react";
import { render, screen } from "@testing-library/react";
import ErrorBoundary from "./ErrorBoundary";

const ThrowError = () => {
  throw new Error("Test error");
};

describe("ErrorBoundary", () => {
  let originalError;

  beforeAll(() => {
    originalError = console.error;
    console.error = jest.fn(); // Suppress React error logs in test output
  });

  afterAll(() => {
    console.error = originalError;
  });

  it("renders children when there is no error", () => {
    render(
      <ErrorBoundary>
        <div data-testid="child">Child Content</div>
      </ErrorBoundary>
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });

  it("renders fallback when error occurs", () => {
    render(
      <ErrorBoundary fallback={<div data-testid="fallback">Error Occurred</div>}>
        <ThrowError />
      </ErrorBoundary>
    );
    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });

  it("renders null by default when error occurs and no fallback is provided", () => {
    const { container } = render(
      <ErrorBoundary>
        <ThrowError />
      </ErrorBoundary>
    );
    expect(container).toBeEmptyDOMElement();
  });
});
