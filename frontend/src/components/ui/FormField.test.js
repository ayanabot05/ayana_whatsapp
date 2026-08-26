import React from "react";
import { render, screen } from "@testing-library/react";
import { FormField } from "./FormField";

describe("FormField", () => {
  it("renders label and children", () => {
    render(
      <FormField label="First Name">
        <input data-testid="input-field" />
      </FormField>
    );
    expect(screen.getByText("First Name")).toBeInTheDocument();
    expect(screen.getByTestId("input-field")).toBeInTheDocument();
  });

  it("renders required indicator when required prop is true", () => {
    render(
      <FormField label="First Name" required>
        <input />
      </FormField>
    );
    expect(screen.getByText("*")).toBeInTheDocument();
  });

  it("renders hint when no error is present", () => {
    render(
      <FormField label="Email" hint="Enter your email address">
        <input />
      </FormField>
    );
    expect(screen.getByText("Enter your email address")).toBeInTheDocument();
  });

  it("renders error message and hides hint when error is present", () => {
    render(
      <FormField label="Email" hint="Enter your email address" error="Invalid email">
        <input />
      </FormField>
    );
    expect(screen.queryByText("Enter your email address")).not.toBeInTheDocument();
    expect(screen.getByText("Invalid email")).toBeInTheDocument();
  });
});
