import React from "react";
import { render, screen } from "@testing-library/react";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders text correctly", () => {
    render(<EmptyState text="No items found." />);
    expect(screen.getByText("No items found.")).toBeInTheDocument();
  });

  it("renders icon if provided", () => {
    render(
      <EmptyState text="Empty" icon={<svg data-testid="test-icon"></svg>} />
    );
    expect(screen.getByTestId("test-icon")).toBeInTheDocument();
    expect(screen.getByText("Empty")).toBeInTheDocument();
  });
});
